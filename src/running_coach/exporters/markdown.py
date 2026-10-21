"""Plain Markdown views of a plan, shared by the CLI and the coach's tools."""

import datetime as dt

from running_coach.domain.athlete import Units
from running_coach.domain.durations import format_duration
from running_coach.domain.plan import PaceTable, PaceZone, Plan, Week, Workout
from running_coach.domain.units import format_distance


def pace_summary(paces: PaceTable, units: Units) -> str:
    lines = [f"- {paces.describe(zone, units)}" for zone in PaceZone if zone != PaceZone.MARATHON]
    basis = f"VDOT {paces.vdot}" if paces.vdot else "effort only, no fitness estimate yet"
    return f"Training paces ({basis}):\n" + "\n".join(lines)


def plan_overview(plan: Plan, today: dt.date | None = None) -> str:
    race = plan.race
    goal = f", goal {format_duration(race.goal_time)}" if race.goal_time else ""
    header = f"# {race.name or race.distance.value} on {race.date:%a %b %d, %Y}{goal} (plan v{plan.version})"
    rows = ["| Week | Starts | Phase | Volume | Long run | Key sessions |", "|---|---|---|---|---|---|"]
    current = plan.week_containing(today) if today else None
    for week in plan.weeks:
        long_run = week.long_run
        key = ", ".join(w.title for w in week.workouts if w.is_hard)
        marker = " ◀ this week" if current and week.number == current.number else ""
        rows.append(
            f"| {week.number}{marker} | {week.start:%b %d} | {week.phase.value.replace('_', ' ')} | "
            f"{format_distance(week.total_km, plan.units)} | "
            f"{format_distance(long_run.distance_km, plan.units) if long_run else '-'} | {key or '-'} |"
        )
    parts = [header, "\n".join(rows), pace_summary(plan.paces, plan.units)]
    if plan.notes:
        parts.append("Notes:\n" + "\n".join(f"- {n}" for n in plan.notes))
    return "\n\n".join(parts)


def workout_line(workout: Workout, plan: Plan) -> str:
    distance = f" ({format_distance(workout.distance_km, plan.units)})" if workout.distance_km else ""
    pace = f" Target: {plan.paces.describe(workout.pace_zone, plan.units)}." if workout.pace_zone else ""
    return f"- **{workout.date:%a %b %d}: {workout.title}**{distance}. {workout.description}{pace}"


def week_detail(week: Week, plan: Plan) -> str:
    header = (
        f"## Week {week.number}: {week.start:%b %d} ({week.phase.value.replace('_', ' ')}, "
        f"{format_distance(week.total_km, plan.units)})"
    )
    lines = [header, week.focus, *(workout_line(w, plan) for w in week.workouts)]
    return "\n".join(lines)
