from datetime import date

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from running_coach.agent.coach import CoachDeps, build_coach, race_countdown
from running_coach.domain.athlete import AthleteProfile


def scripted_model(tool_args: dict) -> FunctionModel:
    """A fake LLM that calls update_profile once, then replies."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("update_profile", {"changes": tool_args})])
        return ModelResponse(parts=[TextPart("Got it!")])

    return FunctionModel(respond)


def test_update_profile_tool_persists_changes(tmp_path):
    deps = CoachDeps.from_data_dir(tmp_path)
    deps.profiles.save(AthleteProfile(first_name="Sam"))
    coach = build_coach(scripted_model({"target_race": {"name": "Spring City Marathon", "date": "2027-04-25"}}))

    result = coach.run_sync("My race is Spring City on April 25", deps=deps)

    assert result.output == "Got it!"
    saved = deps.profiles.load()
    assert saved.first_name == "Sam"
    assert saved.target_race.date == date(2027, 4, 25)


def test_instructions_include_today_and_countdown(tmp_path):
    deps = CoachDeps.from_data_dir(tmp_path, today=date(2026, 10, 20))
    deps.profiles.save(AthleteProfile.model_validate({"target_race": {"date": "2027-04-25"}}))
    seen: list[str] = []

    def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append(messages[0].instructions or "")
        return ModelResponse(parts=[TextPart("hi")])

    build_coach(FunctionModel(capture)).run_sync("hi", deps=deps)

    assert "Tuesday, October 20, 2026" in seen[0]
    assert "187 days to race day" in seen[0]


def test_create_training_plan_tool_saves_a_plan(tmp_path):
    deps = CoachDeps.from_data_dir(tmp_path, today=date(2026, 10, 20))
    deps.profiles.save(
        AthleteProfile.model_validate(
            {"current_weekly_km": 30, "target_race": {"distance": "half_marathon", "date": "2027-02-14"}}
        )
    )

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("create_training_plan", {})])
        return ModelResponse(parts=[TextPart("Here's your plan.")])

    build_coach(FunctionModel(respond)).run_sync("Build my plan", deps=deps)

    plan = deps.plans.load()
    assert plan is not None
    assert plan.weeks[-1].workouts[-1].date == date(2027, 2, 14)


def test_create_training_plan_tool_explains_missing_race(tmp_path):
    deps = CoachDeps.from_data_dir(tmp_path, today=date(2026, 10, 20))
    seen: list[str] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("create_training_plan", {})])
        seen.append(str(messages[-1].parts[0].content))
        return ModelResponse(parts=[TextPart("ok")])

    build_coach(FunctionModel(respond)).run_sync("Build my plan", deps=deps)

    assert "needs the race distance and race date" in seen[0]
    assert deps.plans.load() is None


def test_race_countdown_without_date():
    assert race_countdown(AthleteProfile(), date(2026, 10, 20)) == "No race date set yet."
