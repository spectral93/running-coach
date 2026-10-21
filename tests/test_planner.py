from datetime import date, timedelta

import pytest

from running_coach.domain.athlete import AthleteProfile, RaceDistance
from running_coach.domain.plan import Phase, WorkoutType
from running_coach.engine.guardrails import check_plan
from running_coach.engine.planner import PlanningError, build_plan

TODAY = date(2026, 10, 20)  # a Tuesday

PERSONAS = {
    "returning_from_injury_marathoner": {
        "experience_level": "advanced",
        "current_weekly_km": 20,
        "longest_recent_run_km": 14,
        "current_runs_per_week": 2,
        "preferred_run_days": ["tue", "thu", "sat"],
        "long_run_day": "sat",
        "recent_races": [{"distance": "marathon", "time": "2:55:00", "date": "2026-05-03"}],
        "current_injury": {"description": "Patellofemoral pain", "status": "improving", "expected_clear_date": "2026-12-15"},
        "target_race": {"distance": "marathon", "date": "2027-04-25", "goal_time": "2:50:00"},
    },
    "first_time_marathoner": {
        "experience_level": "beginner",
        "current_weekly_km": 15,
        "longest_recent_run_km": 8,
        "target_race": {"distance": "marathon", "date": "2027-02-14"},
    },
    "intermediate_half": {
        "experience_level": "intermediate",
        "current_weekly_km": 35,
        "longest_recent_run_km": 14,
        "preferred_run_days": ["mon", "tue", "thu", "sat", "sun"],
        "recent_races": [{"distance": "10k", "time": "48:00", "date": "2026-09-20"}],
        "target_race": {"distance": "half_marathon", "date": "2027-01-17", "goal_time": "1:45:00"},
    },
    "new_runner_5k": {
        "experience_level": "new",
        "target_race": {"distance": "5k", "date": "2026-12-19"},
    },
    "short_notice_marathon": {
        "experience_level": "intermediate",
        "current_weekly_km": 40,
        "longest_recent_run_km": 18,
        "target_race": {"distance": "marathon", "date": "2026-12-20"},
    },
    "miles_user_10k": {
        "units": "mi",
        "experience_level": "intermediate",
        "current_weekly_km": 30,
        "recent_races": [{"distance": "5k", "time": "22:30", "date": "2026-10-01"}],
        "target_race": {"distance": "10k", "date": "2027-01-10", "goal_time": "46:00"},
    },
    "advanced_six_days": {
        "experience_level": "advanced",
        "current_weekly_km": 60,
        "longest_recent_run_km": 22,
        "recent_races": [{"distance": "half_marathon", "time": "1:22:00", "date": "2026-10-05"}],
        "target_race": {"distance": "marathon", "date": "2027-03-21", "goal_time": "2:55:00"},
    },
}


@pytest.fixture(params=list(PERSONAS))
def persona(request):
    profile = AthleteProfile.model_validate(PERSONAS[request.param])
    return request.param, profile, build_plan(profile, TODAY)


def test_every_persona_passes_guardrails(persona):
    name, profile, plan = persona
    assert check_plan(plan, profile) == [], name


def test_plan_ends_with_the_race(persona):
    _, profile, plan = persona
    race = plan.weeks[-1].workouts[-1]
    assert race.type == WorkoutType.RACE
    assert race.date == profile.target_race.date
    assert plan.weeks[-1].phase == Phase.RACE_WEEK


def test_weeks_are_consecutive_mondays(persona):
    _, _, plan = persona
    assert plan.weeks[0].start == date(2026, 10, 26)
    for earlier, later in zip(plan.weeks, plan.weeks[1:]):
        assert later.start - earlier.start == timedelta(days=7)
        assert later.start.weekday() == 0


def test_workouts_fall_inside_their_week(persona):
    _, _, plan = persona
    for week in plan.weeks:
        for workout in week.workouts:
            assert week.start <= workout.date < week.start + timedelta(days=7)


def test_at_most_one_run_per_day(persona):
    _, _, plan = persona
    run_dates = [w.date for week in plan.weeks for w in week.runs]
    assert len(run_dates) == len(set(run_dates))


def test_runs_only_on_available_days(persona):
    name, profile, plan = persona
    if not profile.preferred_run_days:
        pytest.skip("default days")
    allowed = {["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(d) for d in profile.preferred_run_days}
    for week in plan.weeks:
        for run in week.runs:
            if run.type != WorkoutType.RACE:
                assert run.date.weekday() in allowed, (name, run)


def test_volume_peaks_before_taper(persona):
    _, _, plan = persona
    taper_weeks = [w for w in plan.weeks if w.phase in (Phase.TAPER, Phase.RACE_WEEK)]
    assert all(w.total_km - (42.2 if w.phase == Phase.RACE_WEEK else 0) < plan.peak_km() for w in taper_weeks)


def test_no_hard_sessions_before_injury_clearance():
    profile = AthleteProfile.model_validate(PERSONAS["returning_from_injury_marathoner"])
    plan = build_plan(profile, TODAY)
    cleared = profile.current_injury.expected_clear_date
    early = [w for week in plan.weeks for w in week.workouts if w.date < cleared]
    assert early and not any(w.is_hard for w in early)
    assert plan.weeks[0].phase == Phase.RETURN_TO_RUN
    assert plan.weeks[0].total_km <= 21  # starts from current volume


def test_returning_runner_rebuilds_run_frequency_gradually():
    profile = AthleteProfile.model_validate(PERSONAS["returning_from_injury_marathoner"])
    plan = build_plan(profile, TODAY)
    assert len(plan.weeks[0].runs) == 2
    assert len(plan.weeks[10].runs) == 3


def test_three_day_runner_is_told_volume_is_capped():
    profile = AthleteProfile.model_validate(PERSONAS["returning_from_injury_marathoner"])
    plan = build_plan(profile, TODAY)
    assert any("3 run days" in note for note in plan.notes)


def test_short_notice_plan_warns():
    profile = AthleteProfile.model_validate(PERSONAS["short_notice_marathon"])
    plan = build_plan(profile, TODAY)
    assert any("compressed" in note for note in plan.notes)


def test_beginner_marathon_long_run_is_capped_at_30km():
    profile = AthleteProfile.model_validate(PERSONAS["first_time_marathoner"])
    plan = build_plan(profile, TODAY)
    assert max(w.long_run.distance_km for w in plan.weeks if w.long_run) <= 30


def test_build_phase_starts_with_fitness_check():
    profile = AthleteProfile.model_validate(PERSONAS["advanced_six_days"])
    plan = build_plan(profile, TODAY)
    checks = [w for week in plan.weeks for w in week.workouts if w.type == WorkoutType.FITNESS_CHECK]
    assert len(checks) == 1


def test_marathon_plan_includes_goal_pace_work():
    profile = AthleteProfile.model_validate(PERSONAS["advanced_six_days"])
    plan = build_plan(profile, TODAY)
    assert any(w.type == WorkoutType.RACE_PACE for week in plan.weeks for w in week.workouts)
    assert plan.paces.race == pytest.approx((2 * 3600 + 55 * 60) / 42.195)


def test_miles_user_gets_miles_in_descriptions():
    profile = AthleteProfile.model_validate(PERSONAS["miles_user_10k"])
    plan = build_plan(profile, TODAY)
    text = " ".join(w.description for week in plan.weeks for w in week.workouts)
    assert " mi " in text and " km " not in text


def test_missing_race_details_raise():
    with pytest.raises(PlanningError):
        build_plan(AthleteProfile(), TODAY)
    past = AthleteProfile.model_validate({"target_race": {"distance": RaceDistance.FIVE_K, "date": "2026-01-01"}})
    with pytest.raises(PlanningError):
        build_plan(past, TODAY)


def test_plan_is_deterministic():
    profile = AthleteProfile.model_validate(PERSONAS["intermediate_half"])
    assert build_plan(profile, TODAY) == build_plan(profile, TODAY)
