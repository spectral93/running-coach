from datetime import date

from running_coach.domain.athlete import AthleteProfile
from running_coach.engine.planner import build_plan
from running_coach.exporters.markdown import plan_overview, week_detail
from running_coach.storage.plan_store import PlanStore

PROFILE = AthleteProfile.model_validate(
    {"current_weekly_km": 25, "target_race": {"name": "Spring Half", "distance": "half_marathon", "date": "2027-03-07"}}
)


def test_saving_bumps_version_and_archives_previous(tmp_path):
    store = PlanStore(tmp_path)
    assert store.load() is None

    first = store.save(build_plan(PROFILE, date(2026, 10, 20)))
    second = store.save(build_plan(PROFILE, date(2026, 11, 2)))

    assert (first.version, second.version) == (1, 2)
    assert store.load().version == 2
    assert (tmp_path / "plan.v1.json").exists()


def test_round_trip_preserves_plan(tmp_path):
    store = PlanStore(tmp_path)
    plan = store.save(build_plan(PROFILE, date(2026, 10, 20)))
    assert store.load() == plan


def test_markdown_views_render():
    plan = build_plan(PROFILE, date(2026, 10, 20))
    overview = plan_overview(plan, date(2026, 11, 3))
    assert "Spring Half" in overview and "◀ this week" in overview
    detail = week_detail(plan.weeks[-1], plan)
    assert "Race day: Spring Half" in detail
