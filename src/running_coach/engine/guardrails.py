"""Hard safety limits for training plans.

The planner is built to respect these, and every plan is checked against them,
including plans edited later by the coach. The LLM cannot override them.
"""

from pydantic import BaseModel

from running_coach.domain.athlete import AthleteProfile, InjuryStatus
from running_coach.domain.plan import Phase, Plan, WorkoutType

# Week-over-week volume growth, compared with the biggest of the previous three
# weeks so that returning to normal after a cutback week is allowed. At low volume
# the 10% rule is needlessly slow, so a few km of growth is always allowed.
MAX_WEEKLY_INCREASE = 0.10
MIN_ALLOWED_INCREASE_KM = 3.0
INCREASE_TOLERANCE_KM = 1.0

# Longest share of the week's volume a single long run may take. Runners on
# fewer days necessarily put a bigger share into the long run; classic novice
# marathon plans put about half of a four-day week into it.
LONG_RUN_SHARE = {1: 1.0, 2: 0.65, 3: 0.55, 4: 0.5, 5: 0.45}
DEFAULT_LONG_RUN_SHARE = 0.4
ABSOLUTE_LONG_RUN_CAP_KM = 35.0

MAX_QUALITY_SESSIONS = 2
# A single hard session (warm-up and cool-down included) may not dominate the week.
MAX_QUALITY_SHARE = 0.35
RACE_WEEK_MAX_FRACTION_OF_PEAK = 0.6


def long_run_share_cap(runs_per_week: int) -> float:
    return LONG_RUN_SHARE.get(runs_per_week, DEFAULT_LONG_RUN_SHARE)


class Violation(BaseModel):
    week: int
    rule: str
    message: str


def check_plan(plan: Plan, profile: AthleteProfile) -> list[Violation]:
    violations: list[Violation] = []

    def flag(week: int, rule: str, message: str) -> None:
        violations.append(Violation(week=week, rule=rule, message=message))

    for i, week in enumerate(plan.weeks):
        if week.phase not in (Phase.TAPER, Phase.RACE_WEEK) and i > 0:
            prior = max(w.total_km for w in plan.weeks[max(0, i - 3) : i])
            limit = prior + max(prior * MAX_WEEKLY_INCREASE, MIN_ALLOWED_INCREASE_KM) + INCREASE_TOLERANCE_KM
            if week.total_km > limit:
                flag(week.number, "volume_increase", f"{week.total_km} km is too big a jump from {prior} km")

        long_run = week.long_run
        if long_run and long_run.distance_km:
            cap = long_run_share_cap(len(week.runs)) * week.total_km + 0.5
            if long_run.distance_km > cap:
                flag(week.number, "long_run_share", f"long run {long_run.distance_km} km is too much of {week.total_km} km")
            if long_run.distance_km > ABSOLUTE_LONG_RUN_CAP_KM:
                flag(week.number, "long_run_cap", f"long run {long_run.distance_km} km exceeds {ABSOLUTE_LONG_RUN_CAP_KM} km")

        quality = [w for w in week.workouts if w.is_hard and w.type != WorkoutType.RACE]
        if len(quality) > MAX_QUALITY_SESSIONS:
            flag(week.number, "too_many_quality", f"{len(quality)} hard sessions in one week")
        for w in quality:
            if (w.distance_km or 0) > MAX_QUALITY_SHARE * week.total_km + 0.5:
                flag(week.number, "quality_share", f"{w.title} ({w.distance_km} km) is too much of {week.total_km} km")

    demanding = sorted(
        (w for week in plan.weeks for w in week.workouts if w.is_hard or w.type == WorkoutType.LONG),
        key=lambda w: w.date,
    )
    for earlier, later in zip(demanding, demanding[1:]):
        if (later.date - earlier.date).days <= 1:
            week = plan.week_containing(later.date)
            flag(week.number if week else 0, "back_to_back", f"hard days on {earlier.date} and {later.date}")

    injury = profile.current_injury
    if injury and injury.status != InjuryStatus.RESOLVED and injury.expected_clear_date:
        for week in plan.weeks:
            for w in week.workouts:
                if w.is_hard and w.type != WorkoutType.RACE and w.date < injury.expected_clear_date:
                    flag(week.number, "intensity_before_clearance", f"{w.title} on {w.date} is before injury clearance")

    if plan.weeks:
        race_week = plan.weeks[-1]
        easy_km = sum(w.distance_km or 0 for w in race_week.runs if w.type != WorkoutType.RACE)
        if easy_km > RACE_WEEK_MAX_FRACTION_OF_PEAK * plan.peak_km():
            flag(race_week.number, "taper", "race week volume is too high")

    return violations
