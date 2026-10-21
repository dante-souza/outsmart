# AGENTS.md

Outsmart is a Streamlit app where 4 LLMs play a 10-turn negotiation game (give 1 coin, take 1 coin,
private messages, alliances). Results go to MongoDB and feed a TrueSkill leaderboard in the sidebar.

## Remotes and deploy

- `origin` is the live Hugging Face Space (`huggingface.co/spaces/ed-donner/outsmart`). Pushing to it deploys.
- `githubrepo` is GitHub (`ed-donner/outsmart`), which is public. Both track `main`.
- Never commit or push unless the owner asks, and check before pushing to either remote.
- To deploy:
  1. `uv run pytest`
  2. Commit.
  3. `git push githubrepo main`
  4. `git push origin main`
  5. Watch the Space's build and container logs.
- HF uses the legacy Streamlit SDK. It reads `sdk_version` and `python_version` from the README frontmatter
  and installs `requirements.txt` with pip. It ignores `pyproject.toml` and `uv.lock`.
- Keep the `streamlit==` pin in `pyproject.toml` equal to `sdk_version` in the README. It is currently
  1.66.1, which builds and runs on HF (confirmed 2026-10-21; Streamlit now serves through Uvicorn).
- After any dependency change, regenerate `requirements.txt`:
  `uv export --format requirements-txt --no-hashes --no-dev -o requirements.txt`
- Space secrets:
  - `OPENROUTER_API_KEY` and `MONGO_URI` are required.
  - `ARENA` must not be set on the Space. With `ARENA=random` the public would play expensive models.
  - The old provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` and the rest) are no longer read.
- HF stopped offering the Streamlit SDK for new Spaces (2025-04-30); existing Spaces still build.
  Docker is the long-term path.
- HF disallows binary files, which is why the header image is `outsmart_image_base64.txt`.
- Two startup messages are expected and harmless:
  - "Collecting usage statistics" in the HF logs is Streamlit telemetry.
  - Streamlit 1.66 shows an "install agent skills" prompt only when all of these hold: the server is not
    headless, a coding agent is installed, and the browser connects over localhost. Linux with no display
    defaults to headless, so it never shows on HF.

## Commands

Use uv only: never pip, never bare `python`.

- `uv sync`: install
- `uv run streamlit run app.py`: run locally at http://localhost:8501
- `uv run pytest`: tests (48, about 5s, no network)
- `uv run black <files>`: format at 88 columns. `game/arenas.py`, `views/headers.py` and
  `views/sidebars.py` weren't black-clean before the modernisation, so don't mass-reformat them unasked.

About `.env`:
- It holds `OPENROUTER_API_KEY`, `MONGO_URI`, optional `ARENA=random`, and many unrelated keys. Never
  print its values.
- The app loads it with `override=True`. So with `MONGO_URI` set, finished local games go to the real
  leaderboard; comment it out to test without saving.
- `load_dotenv()` searches from the calling file's directory, so scripts outside the repo must pass the
  path explicitly.

## Layout

- `app.py`: entry point. Keeps the `Arena` in `st.session_state` and hands off to `views.displays.Display`.
- `game/arenas.py`: `Arena`, the game manager. Turn loop, solvency check, game over, saving, the default
  lineup (`Arena.model_names`) and the rankings filter.
- `game/referees.py`: `Referee` runs one turn. Players move in parallel threads, then giving, taking,
  alliances, and message delivery.
- `game/players.py`: `Player` builds prompts and calls its `LLM` with the move schema.
- `interfaces/llms.py`: the only LLM code. LiteLLM to OpenRouter, with structured outputs and per-model
  reasoning effort.
- `models/moves.py`: `Move`, plus `Move.response_format(other_names)`, which builds the per-player
  Pydantic schema.
- `models/records.py`: `TurnRecord`. Its `__repr__` is the turn recap fed back into later prompts.
- `models/games.py`: `Game` and `Result`. Mongo access (`outsmart.games`) and the leaderboard.
- `prompting/`: system and user prompts. The JSON keys quoted there must match the schema field names.
- `views/`: Streamlit UI (header, buttons, chart, player columns, sidebar leaderboard).
- `tests/`: see Tests.

## Game rules as implemented

- Everyone starts with 12 coins.
- Each turn, every player loses the coin they give, even when their move is invalid, so an invalid move costs 1 coin.
- An alliance means 2 players give to each other and take from the same victim. Each ally gets +1 and the victim -2.
- `give` and `take` must name other players and must differ. Messages to non-players or to yourself are dropped.
  - The schema limits both fields to the other players' names.
  - The schema can't require them to differ, because strict JSON Schema has no constraint across two
    fields. The referee rejects give == take as an invalid move.
- The game ends after turn 10, or when anyone reaches 0 coins (clamped to 0, `kill()`). It is saved exactly once.
- `player.series` (the chart) is appended after the solvency check, so a bankrupt player shows 0, not a negative number.

## LLM layer

- `OPENROUTER_MODELS` maps game model names to OpenRouter ids.
  - The names are stored in Mongo, so keep them stable for leaderboard continuity. Rename only with a
    data migration.
  - New models are named by their OpenRouter id, as `openai/gpt-oss-120b` already was.
- Every model must support structured outputs on OpenRouter. Before adding one, check its endpoints
  (`/api/v1/models/<id>/endpoints`). At least one endpoint must list `structured_outputs`,
  `response_format` and `reasoning`.
- Requests send `extra_body={"provider": {"require_parameters": True}}`. With a `json_schema`
  `response_format`, that limits routing to upstream providers that support structured outputs.
- Every request sends `extra_body["reasoning"] = LLM.reasoning()`, which is OpenRouter's own parameter.
  - The effort is `DEFAULT_REASONING_EFFORT` ("low"), unless the model is in `REASONING_EFFORT`. Currently
    that's DeepSeek and MiMo at "none".
  - Don't use LiteLLM's `reasoning_effort`. LiteLLM forwards it as a top-level field, and some providers
    (all of MiMo's) don't list that field, so `require_parameters` would leave them with no provider.
  - `require_parameters` doesn't enforce `reasoning`: Venice served MiMo without reasoning. Treat the
    effort as a request, not a guarantee.
  - MiMo only has reasoning on or off. For older Claude models that take a token budget, OpenRouter sets
    the budget at "low" to 20% of max_tokens.
- No temperature and no max_tokens. This was a deliberate choice by the owner.
- The schema uses `Literal` enums of the other players' names, and a nested object with one required
  message field per other player. Strict mode rejects `Dict[str, str]`, so don't use free-form dicts in schemas.
- Environment settings made before `import litellm`:
  - `LITELLM_LOCAL_MODEL_COST_MAP=True` stops LiteLLM fetching the model map on import.
  - `LITELLM_DISABLE_REDACT_SECRETS=true` must stay. See below.
- Why the redaction setting must stay:
  - Without it, the import attaches a redaction filter to the Streamlit server's `asyncio` and `uvicorn`
    loggers, and that filter lazily imports more of LiteLLM.
  - If the server logs while a session's script thread is still importing LiteLLM, the threads deadlock
    (`_DeadlockError`). After that, every server log raises `KeyError: 'litellm'`.
  - This crashed the HF Space's first page load on 2026-10-21. A restart only works if it happens to win
    the race.
  - `tests/test_startup.py` reproduces it in a subprocess.
  - The filter exists to scrub API keys from logs for LiteLLM's proxy server. This app doesn't log keys.
- LiteLLM must stay `>=1.83.0`, because 1.82.7 and 1.82.8 were compromised on PyPI (March 2026).
- Importing litellm takes about 1.7s once per process.

## Model choices (researched 2026-10-21)

The default lineup (`Arena.model_names`) is the owner's choice. They want mainstream, fast and cheap models
near the Artificial Analysis (AA) frontier.

| Model | $/M in/out | AA Intelligence Index (v4.3.2) | Reasoning used |
|---|---|---|---|
| `openai/gpt-6-luna` | 0.10/0.50 | 38 at max, 22 at low | low |
| `anthropic/claude-haiku-5.5` | 0.10/0.50 | 43 at max, 29 at low | low |
| `deepseek/deepseek-v4.1-flash-1017` | 0.15/0.60 | 45 at max | none |
| `xiaomi/mimo-v2.6-flash` | 0.14/0.28 | 38 | none |

Considered and rejected:
- **Gemini 3.5 Flash-Lite** (the newest Flash-Lite): AA 22 at $0.30/$2.50. It's the fastest at 433 tok/s,
  but Luna matches its score at low for a fifth of the output price.
- **Gemini 3.8 Flash**: AA 41, but about 8x Haiku's price.
- **Grok:** there's no lite Grok on OpenRouter. Grok 4 Fast and 4.1 Fast were retired there in May 2026,
  and the cheapest left, Grok 4.3, is $1.25/$2.50 with AA 25 and slow time to first token.
  `grok-4` and `grok-4-fast` were dropped from `OPENROUTER_MODELS`.
  `grok-4.20-0309-reasoning` is mapped to `x-ai/grok-4.20`.
- **MiniMax-M3.1-Flash:** AA 43, but only a free variant on OpenRouter, without structured outputs.
- **GLM-5.3-Flash:** AA 42 and cheap, but slow (69 tok/s) and verbose. Z.ai's own endpoint lacks
  structured outputs.

## Live games

These were played on 2026-10-21 with a throwaway script that isn't in the repo.
- It loaded only the OpenRouter key, so the games weren't saved to Mongo.
- It recorded each raw response by wrapping `httpx.Client.send`.
- Costs come from `usage.cost` in each response and from `/api/v1/generation`, which agreed in every game.
- The key's total usage kept rising while nothing was being called, so something else uses that key. A
  dedicated Space key with a credit limit is recommended.

| Settings | Cost | Time | Notes |
|---|---|---|---|
| Everything at low | $0.054 | 1,000s | DeepSeek reasoned 1.5-9k tokens per call and MiMo up to 17.5k, which was 76% of the cost and all of the wait. The worst call was MiMo on Xiaomi's endpoint: 352s at about 50 tok/s. |
| DeepSeek minimal, MiMo none | $0.042 | 359s | MiMo dropped to 3-13s a call. DeepSeek hardly changed at minimal (1-14k reasoning tokens). |
| DeepSeek and MiMo none (current) | $0.026 | 106s | Turns took 6-19s, and each model cost $0.005-0.008. There was one invalid move: DeepSeek gave to and took from the same player after changing its mind mid-strategy. |

Haiku 5.5 and Luna barely reason at low: 0-708 reasoning tokens a call, usually under 300, and 3-12s.
All 120 calls across the three games succeeded, on 14 upstream providers, so the strict nested schema works
for all four models.

## Leaderboard

- `Game.games_df()` calls `Game.leaderboard(count)`, which is `st.cache_data` keyed on the game count.
  It is recalculated only when a game is added.
- As of 2026-10-21 there are about 7,600 games, and a recalculation takes about 2.4s:
  - TrueSkill about 1.8s. It is pure Python and sequential, and the scipy backend is about 10x slower.
  - Mongo fetch about 0.17s.
  - The groupby takes milliseconds.
- Don't build the leaderboard with per-row DataFrame updates. That was the old `Result.update_on`, which took 20s.
- `Arena.rankings()` only shows models that are in `OPENROUTER_MODELS` and have at least
  `Arena.MINIMUM_GAMES` (10) games.
  - Hidden models still count in everyone's TrueSkill ratings.
  - The sidebar text quotes the minimum.
  - On 2026-10-21 that left 3 models showing: `gpt-5-nano`, `openai/gpt-oss-120b` and `claude-haiku-4-5`.
    The four new models had 7 games each from local testing.
- `Result.__init__` folds `claude-3-5-sonnet*` variants into `claude-3.5-sonnet`.
- `Game.reset()` deletes every game. Never call it.

## Tests

Tests never reach a real LLM or Mongo.

- `tests/conftest.py` has an autouse `isolated` fixture. It removes `MONGO_URI` and `ARENA`, sets a fake
  `OPENROUTER_API_KEY`, and makes `pymongo.MongoClient` raise.
- `scripts` patches `litellm.completion` with `tests/fakes.Scripts`, which answers with LiteLLM's
  `mock_response`. Script moves with `scripts.script(Alex=[move("Blake", "Charlie"), ...])`.
  Unscripted players rotate coins, so their coins don't change.
- `test_llms.py` patches `httpx.Client.send`, so it checks the real request LiteLLM builds:
  - the URL
  - auth
  - the model id
  - the strict schema
  - the routing
  - each model's reasoning effort
  - that no temperature or top-level `reasoning_effort` is sent
- `test_arena.py` plays full games with scripted moves, and checks the default lineup is 4 different
  supported models.
- `test_referee.py` covers the turn mechanics and the bug regressions.
- `test_app.py` drives the app with `AppTest` and patches `dotenv.load_dotenv`, otherwise `.env` would bring
  back the real keys.
- `test_leaderboard.py` uses `use_database()`, which stubs `all`, `count` and `latest` and clears the
  leaderboard cache.
- `test_startup.py` imports `interfaces.llms` in a thread of a fresh interpreter while the main thread logs
  to `asyncio`, which reproduces the HF deadlock. The 1ms pause in its logging loop matters: without it the
  loop starves the importing thread and the test takes 90s.
- Bugs get a failing test first, then the fix.
- A live check through OpenRouter costs money and needs the owner's approval.

## Conventions

- Docstrings use `:param x:` / `:return:`.
- No emojis in code or logs.
- Keep the README concise.
- Find the root cause, with evidence, before fixing anything.

## History

October 2026 modernisation, committed as `5df0a00` and deployed to GitHub and HF on 2026-10-21:
- Set up uv (`pyproject.toml`, `uv.lock`, `.python-version` 3.11), and moved Streamlit from 1.36 to 1.66.1.
- Replaced the per-provider clients in `llms.py` with LiteLLM over OpenRouter, using structured outputs.
- Removed temperature everywhere, and set per-model reasoning effort.
- Renamed the prompt JSON keys to snake_case to match the schema.
- Replaced `use_container_width` with `width="stretch"`.
- Set the new default lineup.
- Fixed these bugs, each with a regression test:
  - KeyError on a message to a non-player
  - message to yourself delivered back to you
  - give or take with yourself accepted (with a phantom alliance)
  - double save when a player goes bankrupt on turn 10
  - negative chart value after bankruptcy
- Leaderboard: 23s per click before, now about 2.4s after a new game and 0.06s on repeat clicks.
  Models need 10 games to appear.

Next commit after `5df0a00`: the LiteLLM startup deadlock fix (`LITELLM_DISABLE_REDACT_SECRETS`, with
`tests/test_startup.py`) and this file.

## Open

- The 15 older models in `OPENROUTER_MODELS` haven't been tried live. Only the default four have.
  They matter for `ARENA=random`.
- Something else is using the OpenRouter key in `.env`. The owner should check, and give the Space its
  own key.
- Leftovers: the old `venv/` folder (ignored by git, safe to delete) and a local `alternate` branch.
