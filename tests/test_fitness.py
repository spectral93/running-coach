from datetime import date

import pytest

from running_coach.domain.athlete import AthleteProfile, RaceDistance
from running_coach.engine.fitness import (
    Confidence,
    GoalAssessment,
    estimate_fitness,
    pace_table,
    predict_race_seconds,
    vdot_from_race,
)

TODAY = date(2026, 10, 20)


# Reference values from the published Daniels VDOT tables.
@pytest.mark.parametrize(
    ("vdot", "km", "table_seconds"),
    [(50, 42.195, 3 * 3600 + 10 * 60 + 49), (50, 5, 19 * 60 + 57), (40, 5, 24 * 60 + 8), (60, 21.0975, 1 * 3600 + 18 * 60 + 9)],
)
def test_predictions_match_daniels_tables(vdot, km, table_seconds):
    assert predict_race_seconds(vdot, km) == pytest.approx(table_seconds, abs=25)


def test_vdot_round_trips_with_prediction():
    seconds = predict_race_seconds(52.3, 10)
    assert vdot_from_race(10, seconds) == pytest.approx(52.3, abs=0.01)


def test_training_paces_match_daniels_vdot_50():
    paces = pace_table(50, None, None)
    assert paces.threshold == pytest.approx(255, abs=3)  # 4:15/km
    assert paces.interval == pytest.approx(235, abs=3)  # 3:55/km
    fast, slow = paces.easy
    assert fast == pytest.approx(307, abs=5) and slow == pytest.approx(338, abs=5)  # 5:07-5:38/km


def test_goal_race_pace():
    paces = pace_table(None, RaceDistance.MARATHON, 3 * 3600)
    assert paces.race == pytest.approx(255.97, abs=0.1)
    assert paces.threshold is None


def test_recent_dated_race_gives_high_confidence():
    profile = AthleteProfile.model_validate(
        {"recent_races": [{"distance": "10k", "time": "45:00", "date": "2026-09-01"}]}
    )
    estimate = estimate_fitness(profile, TODAY)
    assert estimate.confidence == Confidence.HIGH
    assert estimate.vdot == pytest.approx(45.3, abs=0.3)


def test_undated_races_are_low_confidence_and_flagged():
    profile = AthleteProfile.model_validate({"recent_races": [{"distance": "marathon", "time": "2:55:00"}]})
    estimate = estimate_fitness(profile, TODAY)
    assert estimate.confidence == Confidence.LOW
    assert any("dates are unknown" in n for n in estimate.notes)


def test_old_races_are_ignored_when_dated():
    profile = AthleteProfile.model_validate(
        {"recent_races": [{"distance": "marathon", "time": "2:55:00", "date": "2019-05-01"}]}
    )
    assert estimate_fitness(profile, TODAY).vdot is None


@pytest.mark.parametrize(
    ("goal", "expected"),
    [("3:30:00", GoalAssessment.CONSERVATIVE), ("3:15:00", GoalAssessment.REALISTIC), ("3:08:00", GoalAssessment.AMBITIOUS), ("2:50:00", GoalAssessment.VERY_AMBITIOUS)],
)
def test_goal_assessment(goal, expected):
    profile = AthleteProfile.model_validate(
        {
            "recent_races": [{"distance": "marathon", "time": "3:20:00", "date": "2026-05-01"}],
            "target_race": {"distance": "marathon", "goal_time": goal},
        }
    )
    assert estimate_fitness(profile, TODAY).goal_assessment == expected
