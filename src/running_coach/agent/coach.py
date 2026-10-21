"""The coach agent: an LLM loop with tools over the runner's stored state.

The model is any pydantic-ai "provider:model" string, so users bring their own LLM.
All training math happens in `running_coach.engine`; the LLM calls it through tools.
"""

import datetime as dt
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model

from running_coach.domain.athlete import AthleteProfile, merge_profile
from running_coach.domain.durations import format_duration
from running_coach.engine.fitness import estimate_fitness, pace_table
from running_coach.engine.guardrails import check_plan
from running_coach.engine.planner import PlanningError, build_plan
from running_coach.exporters.markdown import pace_summary, plan_overview, week_detail
from running_coach.storage.plan_store import PlanStore
from running_coach.storage.profile_store import ProfileStore


@dataclass
class CoachDeps:
    profiles: ProfileStore
    plans: PlanStore
    today: dt.date = field(default_factory=dt.date.today)

    @classmethod
    def from_data_dir(cls, data_dir: Path, today: dt.date | None = None) -> "CoachDeps":
        return cls(profiles=ProfileStore(data_dir), plans=PlanStore(data_dir), today=today or dt.date.today())


def _system_prompt() -> str:
    return resources.files("running_coach.agent.prompts").joinpath("coach_system.md").read_text()


def race_countdown(profile: AthleteProfile, today: dt.date) -> str:
    race = profile.target_race
    if not race or not race.date:
        return "No race date set yet."
    days = (race.date - today).days
    if days < 0:
        return f"The race was {-days} days ago."
    weeks, rem = divmod(days, 7)
    return f"{days} days to race day ({weeks} weeks and {rem} days)."


def build_coach(model: Model | str) -> Agent[CoachDeps, str]:
    agent = Agent(
        model,
        deps_type=CoachDeps,
        instructions=_system_prompt(),
        defer_model_check=True,
    )

    @agent.instructions
    def current_state(ctx: RunContext[CoachDeps]) -> str:
        profile = ctx.deps.profiles.load()
        missing = profile.missing_key_fields()
        lines = [
            f"Today is {ctx.deps.today:%A, %B %d, %Y}.",
            race_countdown(profile, ctx.deps.today),
            "Current athlete profile (JSON):",
            profile.model_dump_json(exclude_defaults=True),
            f"Most useful missing information: {', '.join(missing) if missing else 'none'}.",
        ]
        plan = ctx.deps.plans.load()
        if plan is None:
            lines.append("No training plan yet.")
        else:
            week = plan.week_containing(ctx.deps.today)
            lines.append(f"Training plan v{plan.version} exists ({len(plan.weeks)} weeks).")
            if week:
                lines.append("This week:\n" + week_detail(week, plan))
            elif ctx.deps.today < plan.weeks[0].start:
                lines.append(f"The plan starts on {plan.weeks[0].start:%A %B %d}.")
        return "\n".join(lines)

    @agent.tool
    def update_profile(ctx: RunContext[CoachDeps], changes: AthleteProfile) -> str:
        """Save facts the runner has shared about themselves or their target race.

        Only include fields you learned in this conversation; everything you leave
        out is kept as is. Times use "H:MM:SS" (e.g. "3:45:00").
        """
        updated = merge_profile(ctx.deps.profiles.load(), changes)
        ctx.deps.profiles.save(updated)
        missing = updated.missing_key_fields()
        return f"Saved. Still missing: {', '.join(missing) if missing else 'nothing important'}."

    @agent.tool
    def get_fitness_estimate(ctx: RunContext[CoachDeps]) -> str:
        """Estimate current fitness (VDOT), predicted race times, goal realism and training paces.

        Always use this instead of calculating paces or predictions yourself.
        """
        profile = ctx.deps.profiles.load()
        estimate = estimate_fitness(profile, ctx.deps.today)
        if estimate.vdot is None:
            return "No fitness estimate possible yet. " + " ".join(estimate.notes)
        race = profile.target_race
        predictions = ", ".join(f"{d.value} {format_duration(s)}" for d, s in estimate.predicted_seconds.items())
        lines = [
            f"VDOT {estimate.vdot} ({estimate.confidence.value} confidence), based on {estimate.based_on}.",
            f"Equivalent race times: {predictions}.",
        ]
        if estimate.goal_assessment:
            lines.append(f"Goal needs VDOT {estimate.goal_vdot}: {estimate.goal_assessment.value.replace('_', ' ')}.")
        paces = pace_table(estimate.vdot, race.distance if race else None, race.goal_time if race else None)
        lines.append(pace_summary(paces, profile.units))
        lines += [f"Caveat: {n}" for n in estimate.notes]
        return "\n".join(lines)

    @agent.tool
    def create_training_plan(ctx: RunContext[CoachDeps], start_date: dt.date | None = None) -> str:
        """Build a full training plan from the saved profile and save it as the current plan.

        Confirm the key details with the runner first. Replaces any existing plan
        (the previous version is archived). `start_date` defaults to next Monday.
        """
        profile = ctx.deps.profiles.load()
        try:
            plan = build_plan(profile, ctx.deps.today, start_date)
        except PlanningError as error:
            return f"Could not build a plan: {error}"
        if violations := check_plan(plan, profile):
            problems = "; ".join(f"week {v.week}: {v.message}" for v in violations)
            return f"The plan failed safety checks and was not saved: {problems}"
        plan = ctx.deps.plans.save(plan)
        return plan_overview(plan, ctx.deps.today)

    @agent.tool
    def show_plan_week(ctx: RunContext[CoachDeps], week_number: int | None = None) -> str:
        """Show every workout in one week of the plan. Defaults to the current (or first) week."""
        plan = ctx.deps.plans.load()
        if plan is None:
            return "There is no plan yet."
        if week_number is None:
            week = plan.week_containing(ctx.deps.today) or plan.weeks[0]
        elif 1 <= week_number <= len(plan.weeks):
            week = plan.weeks[week_number - 1]
        else:
            return f"The plan has weeks 1 to {len(plan.weeks)}."
        return week_detail(week, plan)

    @agent.tool
    def show_plan_overview(ctx: RunContext[CoachDeps]) -> str:
        """Show the week-by-week summary of the current plan, its paces and its caveats."""
        plan = ctx.deps.plans.load()
        return plan_overview(plan, ctx.deps.today) if plan else "There is no plan yet."

    return agent
