# Running Coach

An open-source AI running coach for 5K to marathon, aimed at beginner and intermediate
runners chasing their first finish or a goal time. Bring your own LLM: Claude, GPT,
Gemini, or a fully local model through Ollama.

> **Status: early development (Phase 1).** The coach can get to know you, estimate your
> fitness and training paces, and build a full training plan for a 5K, 10K, half or
> marathon. Calendar and PDF export, data imports and plan adjustments are next. See
> [docs/ROADMAP.md](docs/ROADMAP.md).

> **Not medical advice.** This is a training tool, not a doctor. See a medical
> professional before starting a new training program, and for any pain or injury.

## Quick start

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repo> && cd running-coach
cp .env.example .env        # add the API key for your provider
uv run coach chat
```

Other commands:

```bash
uv run coach profile                         # what the coach knows about you
uv run coach plan                            # your plan, week by week
uv run coach plan --week 5                   # every workout in week 5
uv run coach chat --model openai:gpt-5       # use a different model for this session
```

## Choosing a model

Set `model` in [config/coach.yaml](config/coach.yaml) or `COACH_MODEL` in `.env`, using
any [Pydantic AI](https://ai.pydantic.dev/models/) `provider:model` string:

| Provider | Example | Data leaves your machine? |
|---|---|---|
| Anthropic | `anthropic:claude-sonnet-5` | Yes |
| OpenAI | `openai:gpt-5` | Yes |
| Google | `google-gla:gemini-2.5-pro` | Yes |
| Ollama | `ollama:llama3.3` | No |

Your profile and training data are stored locally in `data/`. When you use a cloud model,
the parts of that data the coach needs are sent to the provider.

## How it works

```
src/running_coach/
├── domain/       # data models: athlete, race, plan
├── engine/       # deterministic training science
│   ├── fitness.py      # VDOT fitness estimate, race predictions, training paces
│   ├── planner.py      # profile + race -> week-by-week plan
│   └── guardrails.py   # hard safety limits every plan must pass
├── agent/        # the LLM coach: system prompt and tools
├── exporters/    # plan views (Markdown today; calendar and PDF next)
├── storage/      # local, versioned persistence
└── interfaces/   # CLI today; MCP server and notifications later
```

The key design rule: **the LLM never does the training math.** Paces, mileage progression
and safety limits live in tested code that the coach calls as tools. The LLM does what
it is good at: conversation, judgment and explanation. That is also what makes small or
local models usable.

### How plans are built

- **Fitness** comes from your best recent race, using Jack Daniels' VDOT model (checked
  against the published tables). Without a race, everything is effort-based until a
  5K fitness check.
- **Phases:** return-to-run (only while an injury clears: easy running, no hard
  sessions), base, build, race-specific, taper and race week.
- **Volume** grows by at most about 10% a week (or a few km at low volume), with a
  cutback week every fourth week.
- **Guardrails** cap weekly increases, long-run size, hard sessions per week and
  back-to-back hard days, and block intensity before an injury clearance date. The
  coach cannot save a plan that fails them.
- **Honest notes** flag a compressed timeline, an ambitious goal, a long run that
  falls short of race readiness, or volume limited by too few run days.

## Development

```bash
uv run pytest
```

## License

MIT
