"""Formatting distances and paces in the runner's preferred units."""

from running_coach.domain.athlete import Units

KM_PER_MILE = 1.609344


def format_distance(km: float, units: Units) -> str:
    if units == Units.MI:
        return f"{km / KM_PER_MILE:.1f} mi"
    return f"{km:g} km" if km == int(km) else f"{km:.1f} km"


def format_pace(seconds_per_km: float, units: Units) -> str:
    seconds = seconds_per_km * KM_PER_MILE if units == Units.MI else seconds_per_km
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}/{units.value}"
