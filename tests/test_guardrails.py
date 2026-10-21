from datetime import date

from running_coach.domain.athlete import AthleteProfile
from running_coach.engine.guardrails import check_plan
from running_coach.engine.planner import build_plan

TODAY = date(2026, 10, 20)
PROFILE = AthleteProfile.model_validate(
    {
        "experience_level": "intermediate",
        "current_weekly_km": 40,
        "longest_recent_run_km": 16,
        "target_race": {"distance": "marathon", "date": "2027-03-21"},
    }
)


def rules(plan, profile=PROFILE) -> set[str]:
    return {v.rule for v in check_plan(plan, profile)}


def test_clean_plan_has_no_violations():
    assert rules(build_plan(PROFILE, TODAY)) == set()


def test_flags_big_volume_jump():
    plan = build_plan(PROFILE, TODAY)
    plan.weeks[5].long_run.distance_km += 15
    assert "volume_increase" in rules(plan)


def test_flags_oversized_long_run():
    plan = build_plan(PROFILE, TODAY)
    plan.weeks[-3].long_run.distance_km = 40
    assert {"long_run_cap", "long_run_share"} <= rules(plan)


def test_flags_back_to_back_hard_days():
    plan = build_plan(PROFILE, TODAY)
    week = plan.weeks[10]
    hard = next(w for w in week.workouts if w.is_hard)
    hard.date = week.long_run.date.replace(day=week.long_run.date.day - 1)
    assert "back_to_back" in rules(plan)


def test_flags_intensity_before_injury_clearance():
    plan = build_plan(PROFILE, TODAY)
    injured = PROFILE.model_copy(
        update={"current_injury": {"description": "calf strain", "status": "improving", "expected_clear_date": date(2027, 1, 31)}}
    )
    injured = AthleteProfile.model_validate(injured.model_dump())
    assert "intensity_before_clearance" in rules(plan, injured)


def test_flags_heavy_race_week():
    plan = build_plan(PROFILE, TODAY)
    for w in plan.weeks[-1].runs:
        if w.type.value == "easy":
            w.distance_km = 20
    assert "taper" in rules(plan)
