"""Terminal interface: `coach chat`, `coach profile` and `coach plan`."""

from datetime import date

import typer
from pydantic_ai.exceptions import UserError
from rich.console import Console
from rich.markdown import Markdown

from running_coach.agent.coach import CoachDeps, build_coach, race_countdown
from running_coach.config import load_settings
from running_coach.exporters.markdown import plan_overview, week_detail
from running_coach.storage.plan_store import PlanStore
from running_coach.storage.profile_store import ProfileStore

app = typer.Typer(help="Your bring-your-own-LLM running coach.", no_args_is_help=True)
console = Console()


@app.command()
def chat(model: str = typer.Option(None, help='Override the model, e.g. "openai:gpt-5".')) -> None:
    """Talk to your coach. Type 'exit' to leave."""
    settings = load_settings()
    model_name = model or settings.model
    coach = build_coach(model_name)
    deps = CoachDeps.from_data_dir(settings.data_dir)
    history = []

    console.print(f"[dim]Coach is using {model_name}. Type 'exit' to leave.[/dim]\n")
    greeting = "Hi coach." if deps.profiles.path.exists() else "Hi! I'm new here."
    prompt = greeting
    while True:
        try:
            with console.status("Coach is thinking..."):
                result = coach.run_sync(prompt, deps=deps, message_history=history)
        except UserError as error:
            console.print(f"[red]Could not use model {model_name}:[/red] {error}")
            console.print("Add your provider's API key to .env (see .env.example), or pick another model.")
            raise typer.Exit(1) from error
        history = result.all_messages()
        console.print(Markdown(result.output))
        console.print()
        try:
            prompt = console.input("[bold green]you>[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if prompt.lower() in {"exit", "quit"}:
            break


@app.command()
def profile() -> None:
    """Show what the coach knows about you."""
    store = ProfileStore(load_settings().data_dir)
    current = store.load()
    console.print_json(current.model_dump_json(exclude_defaults=True))
    console.print(race_countdown(current, date.today()))
    if missing := current.missing_key_fields():
        console.print(f"[yellow]Missing:[/yellow] {', '.join(missing)}")


@app.command()
def plan(week: int = typer.Option(None, help="Show every workout in this week number.")) -> None:
    """Show your training plan."""
    current = PlanStore(load_settings().data_dir).load()
    if current is None:
        console.print("No plan yet. Ask your coach to build one in `coach chat`.")
        raise typer.Exit(1)
    if week is None:
        console.print(Markdown(plan_overview(current, date.today())))
    elif 1 <= week <= len(current.weeks):
        console.print(Markdown(week_detail(current.weeks[week - 1], current)))
    else:
        console.print(f"The plan has weeks 1 to {len(current.weeks)}.")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
