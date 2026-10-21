# Roadmap

Dogfood target: **a late-April 2027 marathon (Sunday April 25).**
An 18-week block starts Monday December 21, 2026, and a 3-week taper starts April 4, 2027.
Each phase must be ready before the runner needs it.

| Phase | Scope | Ready by |
|---|---|---|
| 0. Skeleton ✅ | Domain models, config, any-LLM agent, `update_profile` tool, CLI chat, tests | Oct 20, 2026 |
| 1. Training engine ✅ | VDOT fitness estimate, race predictions, pace zones, versioned plan model, plan builder for 5K / 10K / half / full (incl. return-to-run), guardrails, persona tests | Oct 20, 2026 (Nov 8 target) |
| 2. Coach MVP | Plan-editing tools (move, swap, skip, rebuild from a date), recalibrate paces from a new result, SQLite storage, `.ics` and PDF export | Nov 29: **real plan in the calendar** |
| 3. Data and race context | FIT / GPX / Strava-export / Apple Health importers, run log, compliance checks, re-planning, race lookup, Open-Meteo climate and elevation, HR zones, `knowledge/` guides | Dec 20: **block starts** |
| 4. MCP server and evals | Expose coach tools over MCP; persona × scenario eval suite | Jan 2027 |
| 5. Proactive coach | Strava API (webhooks or polling), notifier (Telegram / email / ntfy), check-in rules | Feb 2027 |
| 6. Endgame | Taper and race-week modes, race-day pacing and fueling plan, post-race analysis | Mar 21, 2027 |
| 7. Open-source launch | README polish, Docker, setup wizard, CI, disclaimers, contributing guide | May 2027 |

## Activity data sources

All sources normalize into a single `Activity` model behind one `ActivitySource` interface,
so the coach never cares where a run came from.

| Source | How | Notes |
|---|---|---|
| Files (FIT / GPX / TCX) | Upload or watched folder | Universal baseline; covers Garmin, COROS, Apple Watch exports |
| Strava bulk export | Unzip the account archive | No API terms or approval needed |
| Apple Health | `export.zip` from the Health app | No web API; stream-parse the XML |
| Strava API | User registers their own API app (OAuth) | Enables webhooks for proactive check-ins; check the current API agreement on AI use |
| Strava MCP (official) | `https://mcp.strava.com/mcp` | Claude clients only, Strava subscribers only, read-only, no push. Useful when this coach runs as an MCP server inside Claude, alongside Strava's MCP |

## Dogfooding

Log every bad, generic or unsafe coach response in `COACH_LOG.md`. Each entry becomes an eval case.
