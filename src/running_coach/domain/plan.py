"""A training plan: weeks of workouts plus the pace table they reference.

Workouts name a pace *zone* rather than embedding a pace, so recalibrating the
runner's fitness only means updating the pace table.
"""

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field

from running_coach.domain.athlete import TargetRace, Units
from running_coach.domain.units import format_pace


class PaceZone(StrEnum):
    EASY = "easy"
    MARATHON = "marathon"  # marathon pace at current fitness
    THRESHOLD = "threshold"
    INTERVAL = "interval"
    REPETITION = "repetition"
    RACE = "race"  # goal pace for the target race


ZONE_EFFORT: dict[PaceZone, str] = {
    PaceZone.EASY: "conversational, could chat in full sentences",
    PaceZone.MARATHON: "steady, comfortable for hours",
    PaceZone.THRESHOLD: "comfortably hard, short phrases only",
    PaceZone.INTERVAL: "hard, a few words at a time",
    PaceZone.REPETITION: "fast and relaxed, near mile race pace",
    PaceZone.RACE: "goal race pace",
}


class PaceTable(BaseModel):
    """Seconds per km for each zone. None means the zone is effort-based only."""

    vdot: float | None = None
    easy: tuple[float, float] | None = Field(None, description="(fast end, slow end)")
    marathon: float | None = None
    threshold: float | None = None
    interval: float | None = None
    repetition: float | None = None
    race: float | None = None

    def describe(self, zone: PaceZone, units: Units) -> str:
        effort = ZONE_EFFORT[zone]
        if zone == PaceZone.EASY:
            if self.easy is None:
                return f"easy ({effort})"
            fast, slow = self.easy
            return f"easy, {format_pace(fast, units)[:-3]}–{format_pace(slow, units)} ({effort})"
        pace = getattr(self, zone.value)
        label = f"{zone.value} pace"
        return f"{label} {format_pace(pace, units)} ({effort})" if pace else f"{label} ({effort})"


class Phase(StrEnum):
    RETURN_TO_RUN = "return_to_run"
    BASE = "base"
    BUILD = "build"
    SPECIFIC = "specific"
    TAPER = "taper"
    RACE_WEEK = "race_week"


class WorkoutType(StrEnum):
    EASY = "easy"
    LONG = "long"
    THRESHOLD = "threshold"
    INTERVALS = "intervals"
    RACE_PACE = "race_pace"
    FITNESS_CHECK = "fitness_check"
    RACE = "race"
    STRENGTH = "strength"


HARD_TYPES = {
    WorkoutType.THRESHOLD,
    WorkoutType.INTERVALS,
    WorkoutType.RACE_PACE,
    WorkoutType.FITNESS_CHECK,
    WorkoutType.RACE,
}
RUN_TYPES = HARD_TYPES | {WorkoutType.EASY, WorkoutType.LONG}


class Workout(BaseModel):
    date: dt.date
    type: WorkoutType
    title: str
    description: str
    distance_km: float | None = None
    pace_zone: PaceZone | None = None
    key: bool = Field(False, description="A key session the coach should check in on")

    @property
    def is_run(self) -> bool:
        return self.type in RUN_TYPES

    @property
    def is_hard(self) -> bool:
        return self.type in HARD_TYPES


class Week(BaseModel):
    number: int
    start: dt.date  # Monday
    phase: Phase
    workouts: list[Workout]
    focus: str = ""

    @property
    def total_km(self) -> float:
        return round(sum(w.distance_km or 0 for w in self.workouts if w.is_run), 1)

    @property
    def long_run(self) -> Workout | None:
        return next((w for w in self.workouts if w.type == WorkoutType.LONG), None)

    @property
    def runs(self) -> list[Workout]:
        return [w for w in self.workouts if w.is_run]


class Plan(BaseModel):
    version: int = 1
    created_on: dt.date
    race: TargetRace
    units: Units = Units.KM
    paces: PaceTable
    weeks: list[Week]
    notes: list[str] = Field(default_factory=list, description="Caveats the coach should explain")

    def week_containing(self, day: dt.date) -> Week | None:
        return next((w for w in self.weeks if w.start <= day < w.start + dt.timedelta(days=7)), None)

    def peak_km(self) -> float:
        """Biggest training week, not counting race week."""
        return max((w.total_km for w in self.weeks if w.phase != Phase.RACE_WEEK), default=0.0)
