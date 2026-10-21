"""The athlete profile and their target race.

Every field is optional: the coach works with whatever the runner shares and
asks for the high-value fields (current fitness, race date) first.
"""

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field

from running_coach.domain.durations import Duration


class ExperienceLevel(StrEnum):
    NEW = "new"  # little or no regular running
    BEGINNER = "beginner"  # running regularly, first race at this distance
    INTERMEDIATE = "intermediate"  # a few races done, chasing a time
    ADVANCED = "advanced"


class RaceDistance(StrEnum):
    FIVE_K = "5k"
    TEN_K = "10k"
    HALF_MARATHON = "half_marathon"
    MARATHON = "marathon"


RACE_DISTANCE_KM: dict[RaceDistance, float] = {
    RaceDistance.FIVE_K: 5.0,
    RaceDistance.TEN_K: 10.0,
    RaceDistance.HALF_MARATHON: 21.0975,
    RaceDistance.MARATHON: 42.195,
}


class Weekday(StrEnum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class Units(StrEnum):
    KM = "km"
    MI = "mi"


class CoachTone(StrEnum):
    GENTLE = "gentle"
    BALANCED = "balanced"
    TOUGH_LOVE = "tough_love"


class InjuryStatus(StrEnum):
    ACTIVE = "active"  # can't run normally
    IMPROVING = "improving"  # running reduced volume, in rehab
    RESOLVED = "resolved"


class CurrentInjury(BaseModel):
    description: str
    status: InjuryStatus = InjuryStatus.IMPROVING
    expected_clear_date: dt.date | None = Field(
        None, description="When the runner expects to be cleared for full training; no hard sessions before this"
    )


class RaceResult(BaseModel):
    distance: RaceDistance
    time: Duration
    date: dt.date | None = None


class Location(BaseModel):
    city: str | None = None
    region: str | None = Field(None, description="Province or state, e.g. 'Ontario'")
    country: str | None = None


class TargetRace(BaseModel):
    name: str | None = None
    distance: RaceDistance | None = None
    date: dt.date | None = None
    goal_time: Duration | None = None
    location: Location | None = None


class AthleteProfile(BaseModel):
    first_name: str | None = None
    experience_level: ExperienceLevel | None = None
    age: int | None = Field(None, ge=10, le=100)
    sex: str | None = Field(None, description="As the runner describes it; used for physiology defaults only")
    height_cm: float | None = Field(None, gt=0)
    weight_kg: float | None = Field(None, gt=0)
    location: Location | None = None
    units: Units = Units.KM

    # Current fitness: the most important inputs for building a plan.
    current_weekly_km: float | None = Field(None, ge=0)
    longest_recent_run_km: float | None = Field(None, ge=0)
    recent_races: list[RaceResult] = Field(default_factory=list)
    marathons_completed: int | None = Field(None, ge=0)

    # Schedule.
    preferred_run_days: list[Weekday] = Field(
        default_factory=list, description="Days the runner is available to run once training is in full swing"
    )
    long_run_day: Weekday | None = None
    current_runs_per_week: int | None = Field(None, ge=0, le=14, description="How many days a week they run right now")

    # Health and environment.
    injury_history: str | None = Field(None, description="Past injuries; put anything ongoing in current_injury")
    current_injury: CurrentInjury | None = None
    resting_hr: int | None = Field(None, ge=25, le=120)
    max_hr: int | None = Field(None, ge=120, le=230)
    has_treadmill_access: bool | None = None
    has_gym_access: bool | None = None

    coach_tone: CoachTone = CoachTone.BALANCED
    target_race: TargetRace | None = None

    def missing_key_fields(self) -> list[str]:
        """High-value fields that would most improve the plan, in priority order."""
        race = self.target_race or TargetRace()
        checks = {
            "target race distance": race.distance,
            "race date": race.date,
            "current weekly volume": self.current_weekly_km,
            "longest recent run": self.longest_recent_run_km,
            "a recent race result or time trial": self.recent_races or None,
            "dates of recent races": None if any(not r.date for r in self.recent_races) else True,
            "goal time": race.goal_time,
            "preferred running days": self.preferred_run_days or None,
            "injury history": self.injury_history or self.current_injury,
            "expected clearance date for the current injury": (
                None
                if self.current_injury
                and self.current_injury.status != InjuryStatus.RESOLVED
                and not self.current_injury.expected_clear_date
                else True
            ),
            "location (for climate)": self.location,
        }
        return [name for name, value in checks.items() if value is None]


def merge_profile(current: AthleteProfile, changes: AthleteProfile) -> AthleteProfile:
    """Apply only the fields explicitly set in `changes`, merging nested objects."""

    def merge(base: dict, patch: dict) -> dict:
        out = dict(base)
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = merge(out[key], value)
            else:
                out[key] = value
        return out

    patch = changes.model_dump(exclude_unset=True)
    return AthleteProfile.model_validate(merge(current.model_dump(), patch))
