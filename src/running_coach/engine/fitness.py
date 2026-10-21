"""Running fitness from race results, using Jack Daniels' VDOT model.

VDOT is a single fitness number derived from a race performance. From it we can
predict race times at other distances and derive training paces. The formulas are
Daniels & Gilbert's oxygen-cost and drop-dead equations; percentages for each
training zone are calibrated against the published Daniels tables.
"""

import datetime as dt
from enum import StrEnum
from math import exp, sqrt

from pydantic import BaseModel

from running_coach.domain.athlete import RACE_DISTANCE_KM, AthleteProfile, InjuryStatus, RaceDistance, RaceResult
from running_coach.domain.durations import format_duration
from running_coach.domain.plan import PaceTable


def _vo2_at_velocity(meters_per_min: float) -> float:
    return -4.60 + 0.182258 * meters_per_min + 0.000104 * meters_per_min**2


def _fraction_sustainable(minutes: float) -> float:
    return 0.8 + 0.1894393 * exp(-0.012778 * minutes) + 0.2989558 * exp(-0.1932605 * minutes)


def _velocity_at_vo2(vo2: float) -> float:
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return (-b + sqrt(b * b - 4 * a * c)) / (2 * a)


def vdot_from_race(distance_km: float, seconds: float) -> float:
    minutes = seconds / 60
    return _vo2_at_velocity(distance_km * 1000 / minutes) / _fraction_sustainable(minutes)


def predict_race_seconds(vdot: float, distance_km: float) -> float:
    """Race time at `distance_km` for a runner of the given VDOT (bisection)."""
    low, high = 60.0, 12 * 3600.0
    for _ in range(80):
        mid = (low + high) / 2
        if vdot_from_race(distance_km, mid) > vdot:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _pace_at_fraction(vdot: float, fraction: float) -> float:
    """Seconds per km when running at `fraction` of VDOT."""
    return 60_000 / _velocity_at_vo2(fraction * vdot)


def pace_table(vdot: float | None, race_distance: RaceDistance | None, goal_seconds: int | None) -> PaceTable:
    race_pace = None
    if race_distance and goal_seconds:
        race_pace = goal_seconds / RACE_DISTANCE_KM[race_distance]
    if vdot is None:
        return PaceTable(race=race_pace)
    return PaceTable(
        vdot=round(vdot, 1),
        easy=(_pace_at_fraction(vdot, 0.70), _pace_at_fraction(vdot, 0.62)),
        marathon=predict_race_seconds(vdot, RACE_DISTANCE_KM[RaceDistance.MARATHON]) / 42.195,
        threshold=_pace_at_fraction(vdot, 0.88),
        interval=_pace_at_fraction(vdot, 0.975),
        repetition=_pace_at_fraction(vdot, 1.05),
        race=race_pace,
    )


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GoalAssessment(StrEnum):
    CONSERVATIVE = "conservative"
    REALISTIC = "realistic"
    AMBITIOUS = "ambitious"
    VERY_AMBITIOUS = "very_ambitious"


class FitnessEstimate(BaseModel):
    vdot: float | None
    confidence: Confidence
    based_on: str
    goal_vdot: float | None = None
    goal_assessment: GoalAssessment | None = None
    predicted_seconds: dict[RaceDistance, int] = {}
    notes: list[str] = []


def _race_label(race: RaceResult) -> str:
    when = f" on {race.date:%b %Y}" if race.date else " (date unknown)"
    return f"{race.distance.value} in {format_duration(race.time)}{when}"


def estimate_fitness(profile: AthleteProfile, today: dt.date) -> FitnessEstimate:
    """Best recent race performance, with honest confidence and caveats."""
    notes: list[str] = []
    dated = [r for r in profile.recent_races if r.date and (today - r.date).days <= 548]
    undated = [r for r in profile.recent_races if not r.date]

    def vdot(r: RaceResult) -> float:
        return vdot_from_race(RACE_DISTANCE_KM[r.distance], r.time)

    if dated:
        best = max(dated, key=vdot)
        months = (today - best.date).days / 30.4
        confidence = Confidence.HIGH if months <= 6 else Confidence.MEDIUM
        current, based_on = vdot(best), _race_label(best)
    elif undated:
        best = max(undated, key=vdot)
        confidence, current, based_on = Confidence.LOW, vdot(best), _race_label(best)
        notes.append("Race dates are unknown, so this may be an old best. Ask when each race was.")
    else:
        current, confidence, based_on = None, Confidence.LOW, "no race results"
        notes.append("No race results yet. Paces are effort-based until a fitness check or race.")

    race = profile.target_race
    injury = profile.current_injury
    if current is not None and injury and injury.status != InjuryStatus.RESOLVED:
        notes.append("Coming back from injury: current fitness is likely below this estimate.")
    long_race = race and race.distance in (RaceDistance.HALF_MARATHON, RaceDistance.MARATHON)
    if current is not None and long_race and profile.current_weekly_km is not None and profile.current_weekly_km < 25:
        notes.append("Current volume is low, so fitness has likely dropped. Recalibrate after the fitness check.")

    estimate = FitnessEstimate(vdot=round(current, 1) if current else None, confidence=confidence, based_on=based_on, notes=notes)
    if current is not None:
        estimate.predicted_seconds = {d: round(predict_race_seconds(current, km)) for d, km in RACE_DISTANCE_KM.items()}
    if current is not None and race and race.distance and race.goal_time:
        goal = vdot_from_race(RACE_DISTANCE_KM[race.distance], race.goal_time)
        gap = goal - current
        estimate.goal_vdot = round(goal, 1)
        if gap <= 0:
            estimate.goal_assessment = GoalAssessment.CONSERVATIVE
        elif gap <= 2:
            estimate.goal_assessment = GoalAssessment.REALISTIC
        elif gap <= 4:
            estimate.goal_assessment = GoalAssessment.AMBITIOUS
        else:
            estimate.goal_assessment = GoalAssessment.VERY_AMBITIOUS
    return estimate
