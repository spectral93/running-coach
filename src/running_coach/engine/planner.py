"""Builds a training plan from the athlete profile. Deterministic: no LLM involved.

Structure: an optional return-to-run phase (easy running only, until injury
clearance), then base, build and race-specific phases with a cutback week every
fourth week, then a taper and race week.
"""

import datetime as dt
from dataclasses import dataclass

from running_coach.domain.athlete import (
    RACE_DISTANCE_KM,
    AthleteProfile,
    ExperienceLevel,
    InjuryStatus,
    RaceDistance,
    Weekday,
)
from running_coach.domain.durations import format_duration
from running_coach.domain.plan import PaceTable, PaceZone, Phase, Plan, Week, Workout, WorkoutType
from running_coach.domain.units import format_distance
from running_coach.engine.fitness import estimate_fitness, pace_table
from running_coach.engine.guardrails import ABSOLUTE_LONG_RUN_CAP_KM, MAX_QUALITY_SHARE, long_run_share_cap

L = ExperienceLevel
D = RaceDistance
WEEKDAYS = list(Weekday)

# Peak weekly volume (km) for a runner on five or more days a week.
PEAK_KM = {
    D.MARATHON: {L.NEW: 50, L.BEGINNER: 60, L.INTERMEDIATE: 70, L.ADVANCED: 85},
    D.HALF_MARATHON: {L.NEW: 32, L.BEGINNER: 42, L.INTERMEDIATE: 55, L.ADVANCED: 70},
    D.TEN_K: {L.NEW: 25, L.BEGINNER: 32, L.INTERMEDIATE: 45, L.ADVANCED: 60},
    D.FIVE_K: {L.NEW: 20, L.BEGINNER: 28, L.INTERMEDIATE: 40, L.ADVANCED: 55},
}
# Fewer run days means less sustainable volume.
DAYS_FACTOR = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.9}
LONG_RUN_CAP_KM = {D.MARATHON: 32, D.HALF_MARATHON: 21, D.TEN_K: 16, D.FIVE_K: 12}
NOVICE_LONG_RUN_CAP_KM = {D.MARATHON: 30, D.HALF_MARATHON: 18, D.TEN_K: 13, D.FIVE_K: 10}
DEFAULT_START_KM = {L.NEW: 10, L.BEGINNER: 20, L.INTERMEDIATE: 30, L.ADVANCED: 40}
DEFAULT_DAYS = {
    L.NEW: ["tue", "thu", "sat"],
    L.BEGINNER: ["tue", "thu", "sat", "sun"],
    L.INTERMEDIATE: ["mon", "tue", "thu", "fri", "sun"],
    L.ADVANCED: ["mon", "tue", "wed", "thu", "fri", "sun"],
}
# Volume of the taper weeks before race week, as a fraction of peak.
TAPER_FRACTIONS = {D.MARATHON: [0.75, 0.6], D.HALF_MARATHON: [0.75], D.TEN_K: [], D.FIVE_K: []}
TAPER_LONG_FRACTIONS = [0.65, 0.5]
RACE_WEEK_FRACTION = {D.MARATHON: 0.3, D.HALF_MARATHON: 0.35, D.TEN_K: 0.45, D.FIVE_K: 0.45}
MIN_WEEKS = {D.MARATHON: 12, D.HALF_MARATHON: 8, D.TEN_K: 6, D.FIVE_K: 4}
# Below this peak long run, the runner is underprepared for the distance.
READY_LONG_RUN_KM = {D.MARATHON: 26, D.HALF_MARATHON: 15, D.TEN_K: 8, D.FIVE_K: 5}

WEEKLY_GROWTH = 0.09  # under the 10% guardrail to leave room for rounding
MIN_WEEKLY_GROWTH_KM = 2.5
RETURN_WEEKLY_GROWTH = 0.07
MIN_RETURN_GROWTH_KM = 1.5
CUTBACK_FRACTION = 0.8
DEFAULT_RETURN_WEEKS = 4
MIN_RUN_KM = 3.0
MAX_EASY_RUN_KM = 16.0
WARMUP_COOLDOWN_KM = 4.0
FALLBACK_THRESHOLD_PACE = 300.0  # sec/km, only used to size sessions without a fitness estimate

PAIN_RULE = "Stop if pain rises above 3/10 or changes how you run."

PHASE_FOCUS = {
    Phase.RETURN_TO_RUN: "Rebuild easy running while the injury settles. No hard efforts yet.",
    Phase.BASE: "Aerobic base: mostly easy running, strides and a gentle threshold session.",
    Phase.BUILD: "Build fitness with threshold and interval work while volume grows.",
    Phase.SPECIFIC: "Race-specific work: practise goal pace and fueling.",
    Phase.TAPER: "Volume drops so you arrive fresh. Keep some intensity.",
    Phase.RACE_WEEK: "Rest up, stay sharp, trust the training.",
}


class PlanningError(ValueError):
    pass


def round_half(km: float) -> float:
    return round(km * 2) / 2


def first_monday_on_or_after(day: dt.date) -> dt.date:
    return day + dt.timedelta(days=(7 - day.weekday()) % 7)


def _circular_gap(a: int, b: int) -> int:
    diff = abs(a - b) % 7
    return min(diff, 7 - diff)


def _spread_days(candidates: list[int], fixed: list[int], count: int, min_gap: int = 1) -> list[int]:
    """Greedily pick `count` days from candidates, as far from `fixed` and each other as possible."""
    chosen: list[int] = []
    pool = [d for d in candidates if d not in fixed]
    while len(chosen) < count and pool:
        taken = fixed + chosen
        best = max(pool, key=lambda d: (min((_circular_gap(d, t) for t in taken), default=7), -d))
        if taken and min(_circular_gap(best, t) for t in taken) < min_gap:
            break
        chosen.append(best)
        pool.remove(best)
    return sorted(chosen)


@dataclass
class _Context:
    profile: AthleteProfile
    distance: RaceDistance
    level: ExperienceLevel
    paces: PaceTable
    days: list[int]  # weekday indexes available to run
    long_day: int

    def fmt(self, km: float) -> str:
        return format_distance(km, self.profile.units)

    @property
    def injured(self) -> bool:
        injury = self.profile.current_injury
        return bool(injury and injury.status != InjuryStatus.RESOLVED)


def _phases(n_weeks: int, start: dt.date, ctx: _Context, notes: list[str]) -> list[Phase]:
    taper = len(TAPER_FRACTIONS[ctx.distance])
    pre = max(0, n_weeks - 1 - taper)

    return_weeks = 0
    injury = ctx.profile.current_injury
    if ctx.injured:
        if injury.expected_clear_date:
            while return_weeks < pre and start + dt.timedelta(weeks=return_weeks) < injury.expected_clear_date:
                return_weeks += 1
        else:
            return_weeks = min(pre, DEFAULT_RETURN_WEEKS)
            notes.append(
                f"No injury clearance date given, so the plan assumes {DEFAULT_RETURN_WEEKS} weeks of easy "
                "return-to-run. Update it once your physio gives a date."
            )
        if injury.status == InjuryStatus.ACTIVE:
            notes.append("The plan assumes you are cleared for easy running. Confirm with your physio or doctor first.")

    normal = pre - return_weeks
    specific = min(round(normal * 0.35), 6 if ctx.distance == D.MARATHON else 4)
    if normal >= 3:
        specific = max(specific, 2)
    novice = ctx.level in (L.NEW, L.BEGINNER)
    base = round(normal * 0.3) if normal >= 8 else (normal - specific) // 2 if novice else 0
    build = normal - specific - base
    return (
        [Phase.RETURN_TO_RUN] * return_weeks
        + [Phase.BASE] * base
        + [Phase.BUILD] * build
        + [Phase.SPECIFIC] * specific
        + [Phase.TAPER] * taper
        + [Phase.RACE_WEEK]
    )


def _warmup_km(weekly_km: float) -> float:
    """Warm-up plus cool-down distance, scaled down for small weeks."""
    return min(WARMUP_COOLDOWN_KM, max(2.0, round_half(weekly_km * 0.12)))


def _threshold_session(ctx: _Context, day: dt.date, weekly_km: float, phase: Phase) -> Workout:
    minutes = min(40, max(16, round(weekly_km * 0.45)))
    if phase == Phase.BASE:
        minutes = min(minutes, 24)
    rep = 8 if minutes < 30 else 10
    reps = max(2, round(minutes / rep))
    pace = ctx.paces.threshold or FALLBACK_THRESHOLD_PACE
    warmup = _warmup_km(weekly_km)
    km = warmup + reps * rep * 60 / pace + (reps - 1) * 0.2
    return Workout(
        date=day,
        type=WorkoutType.THRESHOLD,
        title=f"Threshold: {reps} x {rep} min",
        description=(
            f"{ctx.fmt(warmup / 2)} easy warm-up, then {reps} x {rep} min at threshold with 1 min easy jog between, "
            f"then {ctx.fmt(warmup / 2)} easy cool-down."
        ),
        distance_km=round_half(km),
        pace_zone=PaceZone.THRESHOLD,
        key=True,
    )


def _interval_session(ctx: _Context, day: dt.date, weekly_km: float) -> Workout:
    work_km = min(8.0, max(2.0, weekly_km * 0.08))
    rep_m = 400 if work_km < 3 else 800 if work_km <= 4 else 1000
    recovery_m = 200 if rep_m == 400 else 400
    reps = max(4, round(work_km * 1000 / rep_m))
    warmup = _warmup_km(weekly_km)
    km = warmup + reps * (rep_m + recovery_m) / 1000
    return Workout(
        date=day,
        type=WorkoutType.INTERVALS,
        title=f"Intervals: {reps} x {rep_m} m",
        description=(
            f"{ctx.fmt(warmup / 2)} easy warm-up with 4 strides, then {reps} x {rep_m} m at interval pace with "
            f"{recovery_m} m easy jog between, then {ctx.fmt(warmup / 2)} easy cool-down."
        ),
        distance_km=round_half(km),
        pace_zone=PaceZone.INTERVAL,
        key=True,
    )


def _race_pace_session(ctx: _Context, day: dt.date, weekly_km: float, scale: float = 1.0) -> Workout:
    if ctx.distance == D.MARATHON:
        work = min(16.0, max(6.0, weekly_km * 0.2)) * scale
        structure = f"{ctx.fmt(round_half(work))} continuous at goal marathon pace"
    else:
        work = min(12.0, max(4.0, weekly_km * 0.15)) * scale
        blocks = 2 if work < 8 else 3
        structure = f"{blocks} x {ctx.fmt(round_half(work / blocks))} at goal race pace with 3 min easy jog between"
    warmup = _warmup_km(weekly_km)
    return Workout(
        date=day,
        type=WorkoutType.RACE_PACE,
        title="Goal race pace",
        description=(
            f"{ctx.fmt(warmup / 2)} easy warm-up, then {structure}, then {ctx.fmt(warmup / 2)} easy cool-down. "
            "Practise your race-day fueling and gear."
        ),
        distance_km=round_half(warmup + work),
        pace_zone=PaceZone.RACE,
        key=True,
    )


def _fitness_check(ctx: _Context, day: dt.date, weekly_km: float) -> Workout:
    warmup = _warmup_km(weekly_km)
    return Workout(
        date=day,
        type=WorkoutType.FITNESS_CHECK,
        title="Fitness check: 5K time trial",
        description=(
            f"{ctx.fmt(warmup / 2)} easy warm-up with 4 strides, then run 5K as fast as you can hold evenly, then "
            f"{ctx.fmt(warmup / 2)} easy cool-down. Tell your coach your time so paces can be recalibrated."
        ),
        distance_km=round_half(5 + warmup),
        key=True,
    )


def _strength(ctx: _Context, day: dt.date, phase: Phase, with_run: bool) -> Workout:
    if phase in (Phase.TAPER, Phase.RACE_WEEK):
        body = "Light maintenance, 20 min: bodyweight squats, glute bridges, calf raises, planks. Nothing to failure."
    elif phase in (Phase.RETURN_TO_RUN, Phase.BASE) or ctx.level == L.NEW:
        body = (
            "30 min, 2-3 sets of 10-12: goblet squats, split squats, step-downs, single-leg glute bridges, "
            "calf raises, side planks."
        )
    else:
        body = (
            "30-40 min, 3 sets of 5-8 with heavier load: squats or trap-bar deadlifts, Bulgarian split squats, "
            "single-leg calf raises, plus core work."
        )
    if ctx.injured:
        body += " Include your physio's rehab exercises and skip anything that aggravates the injury."
    return Workout(
        date=day,
        type=WorkoutType.STRENGTH,
        title="Strength" + (" (after your run)" if with_run else ""),
        description=body,
    )


def _easy(ctx: _Context, day: dt.date, km: float, phase: Phase, strides: bool, pickups: bool = False) -> Workout:
    text = "Easy running."
    if pickups:
        text += " Include 6 x 1 min pickups to a comfortably hard effort, with 2 min easy between."
    elif strides:
        text += " Finish with 6 x 20 s relaxed strides with full recovery."
    if phase == Phase.RETURN_TO_RUN:
        text += " " + PAIN_RULE
    return Workout(date=day, type=WorkoutType.EASY, title="Easy run", description=text, distance_km=round_half(km), pace_zone=PaceZone.EASY)


def _long(ctx: _Context, day: dt.date, km: float, phase: Phase, finish_km: float = 0) -> Workout:
    text = "Long run at easy effort."
    if km >= 16:
        text += " Practise fueling: take carbs every 30-40 min once you're past 60 min."
    title = "Long run"
    if finish_km:
        text = (
            f"Long run: run easy, then finish the last {ctx.fmt(finish_km)} at goal marathon pace. "
            "Rehearse race-day fueling and gear."
        )
        title = "Long run with goal-pace finish"
    if phase == Phase.RETURN_TO_RUN:
        text = "Long run at easy effort. " + PAIN_RULE
    return Workout(date=day, type=WorkoutType.LONG, title=title, description=text, distance_km=round_half(km), pace_zone=PaceZone.EASY, key=True)


def _race_week(ctx: _Context, start: dt.date, peak_km: float) -> list[Workout]:
    race = ctx.profile.target_race
    race_day = race.date
    goal = f" Goal: {format_duration(race.goal_time)}." if race.goal_time else ""
    workouts = [
        Workout(
            date=race_day,
            type=WorkoutType.RACE,
            title=f"Race day: {race.name or ctx.distance.value}",
            description=f"Start controlled, settle into goal pace, follow your fueling plan.{goal} Enjoy it.",
            distance_km=RACE_DISTANCE_KM[ctx.distance],
            pace_zone=PaceZone.RACE,
            key=True,
        )
    ]
    run_days = [d for d in ctx.days if start + dt.timedelta(days=d) < race_day][-3:]
    if run_days:
        per_run = max(MIN_RUN_KM, peak_km * RACE_WEEK_FRACTION[ctx.distance] / len(run_days))
        for i, d in enumerate(run_days):
            day = start + dt.timedelta(days=d)
            km = min(per_run, 5.0) if (race_day - day).days <= 2 else per_run
            workouts.append(_easy(ctx, day, km, Phase.RACE_WEEK, strides=i == len(run_days) - 1))
    return sorted(workouts, key=lambda w: w.date)


def build_plan(profile: AthleteProfile, today: dt.date, start: dt.date | None = None) -> Plan:
    race = profile.target_race
    if not race or not race.distance or not race.date:
        raise PlanningError("A plan needs the race distance and race date.")
    if race.date < today:
        raise PlanningError("The race date is in the past.")

    level = profile.experience_level or ExperienceLevel.BEGINNER
    distance = race.distance
    race_monday = race.date - dt.timedelta(days=race.date.weekday())
    start = min(start or first_monday_on_or_after(today), race_monday)
    start -= dt.timedelta(days=start.weekday())
    n_weeks = (race_monday - start).days // 7 + 1

    day_names = profile.preferred_run_days or [Weekday(d) for d in DEFAULT_DAYS[level]]
    days = sorted({WEEKDAYS.index(d) for d in day_names})
    if profile.long_run_day:
        long_day = WEEKDAYS.index(profile.long_run_day)
    else:
        long_day = next((d for d in (6, 5) if d in days), days[-1])
    days = sorted(set(days) | {long_day})

    notes: list[str] = []
    fitness = estimate_fitness(profile, today)
    paces = pace_table(fitness.vdot, distance, race.goal_time)
    ctx = _Context(profile=profile, distance=distance, level=level, paces=paces, days=days, long_day=long_day)
    notes += fitness.notes
    if n_weeks < MIN_WEEKS[distance]:
        notes.append(
            f"Only {n_weeks} weeks to race day; {MIN_WEEKS[distance]}+ is recommended. "
            "The plan is compressed, so consider a more conservative goal."
        )
    if fitness.goal_assessment:
        notes.append(f"Goal looks {fitness.goal_assessment.value.replace('_', ' ')} against current fitness.")

    phases = _phases(n_weeks, start, ctx, notes)
    novice = level in (L.NEW, L.BEGINNER)
    days_factor = DAYS_FACTOR.get(len(days), 1.0)
    peak = PEAK_KM[distance][level] * days_factor
    if days_factor < 1:
        notes.append(
            f"With {len(days)} run days a week, peak volume is capped near {ctx.fmt(round(peak))}. "
            "Adding a run day would support a faster goal."
        )
    current_km = profile.current_weekly_km or DEFAULT_START_KM[level]
    peak = max(peak, current_km)
    long_cap = min((NOVICE_LONG_RUN_CAP_KM if novice else LONG_RUN_CAP_KM)[distance], ABSOLUTE_LONG_RUN_CAP_KM)

    weeks: list[Week] = []
    long_km = profile.longest_recent_run_km or current_km * 0.35
    normal_index = 0  # counts weeks after return-to-run, for cutbacks and session rotation
    peak_long = long_km
    taper_index = 0
    fitness_check_done = False

    for i, phase in enumerate(phases):
        week_start = start + dt.timedelta(weeks=i)
        if phase == Phase.RACE_WEEK:
            peak_km = max((w.total_km for w in weeks), default=current_km)
            workouts = _race_week(ctx, week_start, peak_km)
            weeks.append(Week(number=i + 1, start=week_start, phase=phase, workouts=workouts, focus=PHASE_FOCUS[phase]))
            continue

        cutback = phase in (Phase.BASE, Phase.BUILD, Phase.SPECIFIC) and normal_index % 4 == 3
        # Grow from what was actually scheduled recently, the same reference the guardrail uses.
        reference = max((w.total_km for w in weeks[-3:]), default=current_km)
        if phase == Phase.TAPER:
            peak_km = max(w.total_km for w in weeks)
            target = peak_km * TAPER_FRACTIONS[distance][taper_index]
            week_long = peak_long * TAPER_LONG_FRACTIONS[taper_index]
            taper_index += 1
        elif i == 0:
            target = current_km
        elif cutback:
            target = reference * CUTBACK_FRACTION
        elif phase == Phase.RETURN_TO_RUN:
            target = min(reference + max(reference * RETURN_WEEKLY_GROWTH, MIN_RETURN_GROWTH_KM), peak)
        else:
            target = min(reference + max(reference * WEEKLY_GROWTH, MIN_WEEKLY_GROWTH_KM), peak)

        if phase == Phase.RETURN_TO_RUN:
            runs = min(len(days), max(2, (profile.current_runs_per_week or len(days)) + i // 2))
        else:
            runs = len(days)
        share_cap = long_run_share_cap(runs)
        if phase != Phase.TAPER:
            step = 1.0 if phase == Phase.RETURN_TO_RUN else 2.0
            if cutback:
                week_long = long_km * 0.75
            else:
                long_km = min(long_km + (step if i > 0 else 0), long_cap, share_cap * target)
                week_long = long_km
                peak_long = max(peak_long, long_km)
        week_long = round_half(min(week_long, share_cap * target))

        others = _spread_days(days, [long_day], runs - 1)
        if phase == Phase.RETURN_TO_RUN or (phase == Phase.BASE and novice):
            n_quality = 0
        elif level == L.NEW:
            n_quality = 1 if phase in (Phase.SPECIFIC, Phase.TAPER) else 0
        elif phase in (Phase.BASE, Phase.TAPER) or novice or runs <= 4:
            n_quality = 1
        else:
            n_quality = 2
        quality_days = _spread_days(others, [long_day], n_quality, min_gap=2)

        quality: list[Workout] = []
        for q, d in enumerate(quality_days):
            day = week_start + dt.timedelta(days=d)
            if phase == Phase.BASE:
                quality.append(_threshold_session(ctx, day, target, phase))
            elif phase == Phase.TAPER:
                if distance in (D.FIVE_K, D.TEN_K):
                    quality.append(_interval_session(ctx, day, target))
                elif race.goal_time:
                    quality.append(_race_pace_session(ctx, day, target, scale=0.6))
                else:
                    quality.append(_threshold_session(ctx, day, target * 0.6, phase))
            elif phase == Phase.BUILD and not fitness_check_done and not cutback and q == 0:
                quality.append(_fitness_check(ctx, day, target))
            elif phase == Phase.BUILD:
                use_threshold = (normal_index + q) % 2 == 0
                quality.append(
                    _threshold_session(ctx, day, target, phase) if use_threshold else _interval_session(ctx, day, target)
                )
            else:  # specific
                if distance in (D.FIVE_K, D.TEN_K):
                    quality.append(_interval_session(ctx, day, target) if q == 0 else _threshold_session(ctx, day, target, phase))
                elif race.goal_time and (normal_index + q) % 2 == 0:
                    quality.append(_race_pace_session(ctx, day, target))
                else:
                    quality.append(_threshold_session(ctx, day, target, phase))

        # Sessions too big for this week's volume become easy runs with pickups.
        pickup_days = {
            (w.date - week_start).days for w in quality if w.distance_km > MAX_QUALITY_SHARE * target
        }
        quality = [w for w in quality if (w.date - week_start).days not in pickup_days]
        quality_days = [d for d in quality_days if d not in pickup_days]
        if any(w.type == WorkoutType.FITNESS_CHECK for w in quality):
            fitness_check_done = True

        easy_days = [d for d in others if d not in quality_days]
        remaining = target - week_long - sum(w.distance_km for w in quality)
        # Prefer a slightly shorter long run over dropping a run day entirely.
        shortfall = MIN_RUN_KM * len(easy_days) - remaining
        if easy_days and shortfall > 0 and week_long - shortfall >= MIN_RUN_KM * 1.5:
            week_long = round_half(week_long - shortfall - 0.25)
            remaining = target - week_long - sum(w.distance_km for w in quality)
        while easy_days and remaining / len(easy_days) < MIN_RUN_KM:
            easy_days.remove(next((d for d in reversed(easy_days) if d not in pickup_days), easy_days[-1]))
        strides_day = next((d for d in reversed(easy_days) if d not in pickup_days), None)
        if phase == Phase.RETURN_TO_RUN:
            strides_day = None
        easy_km = 0.0
        if easy_days:
            easy_km = min(remaining / len(easy_days), MAX_EASY_RUN_KM, week_long)
        easy = [
            _easy(ctx, week_start + dt.timedelta(days=d), easy_km, phase, strides=d == strides_day, pickups=d in pickup_days)
            for d in easy_days
        ]

        finish_km = 0.0
        if (
            phase == Phase.SPECIFIC
            and distance == D.MARATHON
            and not novice
            and race.goal_time
            and not cutback
            and normal_index % 2 == 1
        ):
            finish_km = round_half(min(10.0, week_long * 0.3))
        long_run = _long(ctx, week_start + dt.timedelta(days=long_day), week_long, phase, finish_km)

        # Capped easy runs can leave the long run too big a share of the week; trim it to fit.
        others_km = sum(w.distance_km for w in [*quality, *easy])
        while long_run.distance_km > MIN_RUN_KM and long_run.distance_km > share_cap * (long_run.distance_km + others_km):
            long_run.distance_km -= 0.5
        if phase != Phase.TAPER and not cutback:
            long_km = min(long_km, long_run.distance_km)

        run_days = {long_day, *quality_days, *easy_days}
        strength_sessions = 1 if phase == Phase.TAPER else 2
        rest_days = [d for d in range(7) if d not in run_days]
        strength_days = _spread_days(rest_days, sorted(run_days), strength_sessions)
        with_run = [d for d in easy_days if d not in strength_days][: strength_sessions - len(strength_days)]
        strength = [_strength(ctx, week_start + dt.timedelta(days=d), phase, with_run=False) for d in strength_days]
        strength += [_strength(ctx, week_start + dt.timedelta(days=d), phase, with_run=True) for d in with_run]

        workouts = sorted([long_run, *quality, *easy, *strength], key=lambda w: (w.date, not w.is_run))
        focus = PHASE_FOCUS[phase] + (" Cutback week: absorb the training." if cutback else "")
        weeks.append(Week(number=i + 1, start=week_start, phase=phase, workouts=workouts, focus=focus))
        if phase != Phase.RETURN_TO_RUN:
            normal_index += 1

    longest = max((w.long_run.distance_km for w in weeks if w.long_run), default=0)
    if longest < READY_LONG_RUN_KM[distance]:
        notes.append(
            f"The longest run only reaches {ctx.fmt(longest)}, short of the {ctx.fmt(READY_LONG_RUN_KM[distance])} "
            "that prepares you well for this distance. A later race, or more weekly running, would help."
        )
    return Plan(created_on=today, race=race, units=profile.units, paces=paces, weeks=weeks, notes=notes)
