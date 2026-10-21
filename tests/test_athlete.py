from datetime import date

import pytest

from running_coach.domain.athlete import AthleteProfile, RaceDistance, merge_profile
from running_coach.domain.durations import format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("3:45:00", 13500), ("24:30", 1470), ("1:05:07", 3907), (1800, 1800)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("bad", ["", "abc", "1:2:3:4", "-5:00", 0, True])
def test_parse_duration_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)


def test_format_duration_round_trips():
    assert format_duration(13500) == "3:45:00"
    assert format_duration(1470) == "24:30"


def test_goal_time_serializes_as_clock_string():
    profile = AthleteProfile.model_validate({"target_race": {"goal_time": "3:30:00"}})
    assert profile.target_race.goal_time == 12600
    assert profile.model_dump(mode="json")["target_race"]["goal_time"] == "3:30:00"


def test_merge_keeps_existing_and_merges_nested():
    current = AthleteProfile.model_validate(
        {"first_name": "Sam", "target_race": {"name": "Spring City Marathon", "distance": "marathon"}}
    )
    changes = AthleteProfile.model_validate({"target_race": {"date": "2027-04-25"}, "current_weekly_km": 30})
    merged = merge_profile(current, changes)
    assert merged.first_name == "Sam"
    assert merged.current_weekly_km == 30
    assert merged.target_race.name == "Spring City Marathon"
    assert merged.target_race.distance == RaceDistance.MARATHON
    assert merged.target_race.date == date(2027, 4, 25)


def test_missing_fields_shrink_as_profile_fills():
    empty = AthleteProfile()
    assert empty.missing_key_fields()[0] == "target race distance"
    filled = AthleteProfile.model_validate({"target_race": {"distance": "marathon", "date": "2027-04-25"}})
    assert "race date" not in filled.missing_key_fields()
