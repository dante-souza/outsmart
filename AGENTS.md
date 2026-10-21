# AGENTS.md

Outsmart is a Streamlit app where 4 LLMs play a 10-turn negotiation game (give 1 coin, take 1 coin,
private messages, alliances). Results go to MongoDB and feed a TrueSkill leaderboard in the sidebar.

## Remotes and deploy

- `origin` is the live Hugging Face Space (`huggingface.co/spaces/ed-donner/outsmart`). Pushing to it deploys.
- `githubrepo` is GitHub (`ed-donner/outsmart`).
- Never commit or push unless the owner asks, and check before pushing to either remote.
- HF uses the legacy Streamlit SDK. It reads `sdk_version` and `python_version` from the README frontmatter
  and installs `requirements.txt` with pip. It ignores `pyproject.toml` and `uv.lock`.
- Keep the `streamlit==` pin in `pyproject.toml` equal to `sdk_version` in the README.
- After any dependency change, regenerate `requirements.txt`:
  `uv export --format requirements-txt --no-hashes --no-dev -o requirements.txt`
- The Space needs `OPENROUTER_API_KEY` and `MONGO_URI` secrets.
- HF stopped offering the Streamlit SDK for new Spaces (2025-04-30); existing Spaces still build.
  Docker is the long-term path.
- HF disallows binary files, which is why the header image is `outsmart_image_base64.txt`.

## Commands

Use uv only: never pip, never bare `python`.

- `uv sync`: install
- `uv run streamlit run app.py`: run locally
- `uv run pytest`: tests (about 3s, no network)
- `uv run black <files>`: format. HEAD was mostly black-clean at 88 columns. `game/arenas.py`,
  `views/headers.py` and `views/sidebars.py` are not, so don't mass-reformat them unasked.

`.env` holds `OPENROUTER_API_KEY`, `MONGO_URI`, optional `ARENA=random`, and many unrelated keys.
Never print its values. `load_dotenv()` searches from the calling file's directory, so scripts outside
the repo must pass the path explicitly.

## Layout

- `app.py`: entry point. Keeps the `Arena` in `st.session_state` and hands off to `views.displays.Display`.
- `game/arenas.py`: `Arena`, the game manager. Turn loop, solvency check, game over, saving, and the
  default lineup (`Arena.model_names`).
- `game/referees.py`: `Referee` runs one turn. Players move in parallel threads, then giving, taking,
  alliances, and message delivery.
- `game/players.py`: `Player` builds prompts and calls its `LLM` with the move schema.
- `interfaces/llms.py`: the only LLM code. LiteLLM to OpenRouter, with structured outputs.
- `models/moves.py`: `Move`, plus `Move.response_format(other_names)`, which builds the per-player
  Pydantic schema.
- `models/records.py`: `TurnRecord`. Its `__repr__` is the turn recap fed back into later prompts.
- `models/games.py`: `Game` and `Result`. Mongo access (`outsmart.games`) and the leaderboard.
- `prompting/`: system and user prompts. The JSON keys quoted there must match the schema field names.
- `views/`: Streamlit UI (header, buttons, chart, player columns, sidebar leaderboard).

## Game rules as implemented

- Everyone starts with 12 coins.
- Each turn, every player loses the coin they give, even when their move is invalid, so an invalid move costs 1 coin.
- An alliance means 2 players give to each other and take from the same victim. Each ally gets +1 and the victim -2.
- `give` and `take` must name other players and must differ. Messages to non-players or to yourself are dropped.
- The game ends after turn 10, or when anyone reaches 0 coins (clamped to 0, `kill()`). It is saved exactly once.
- `player.series` (the chart) is appended after the solvency check, so a bankrupt player shows 0, not a negative number.

## LLM layer

- `OPENROUTER_MODELS` maps game model names to OpenRouter ids. The names are stored in Mongo, so keep
  them stable for leaderboard continuity. Rename only with a data migration.
- `Arena.rankings()` only shows models still in this dict. Removing a model hides its history.
- Every model must support structured outputs on OpenRouter.
- Requests send `extra_body={"provider": {"require_parameters": True}}`, so OpenRouter only routes to
  upstream providers that support every parameter, including `response_format`.
- Every request sends `extra_body["reasoning"] = LLM.reasoning()`, which is OpenRouter's own parameter.
  - The effort is `DEFAULT_REASONING_EFFORT` ("low"), unless the model is in `REASONING_EFFORT`. Currently
    that's DeepSeek and MiMo at "none".
  - Don't use LiteLLM's `reasoning_effort`. LiteLLM forwards it as a top-level field, and some providers
    (all of MiMo's) don't list that field, so `require_parameters` would leave them with no provider.
- MiMo only has reasoning on or off. For older Claude models that take a token budget, OpenRouter sets the
  budget at "low" to 20% of max_tokens.
- No temperature and no max_tokens. This was a deliberate choice by the owner.
- Before adding a model, check its OpenRouter endpoints (`/api/v1/models/<id>/endpoints`). At least one
  endpoint must list `structured_outputs`, `response_format` and `reasoning`.
- New models are named by their OpenRouter id, as `openai/gpt-oss-120b` already was.
- The schema uses `Literal` enums of the other players' names, and a nested object with one required
  message field per other player. Strict mode rejects `Dict[str, str]`, so don't use free-form dicts in schemas.
- `LITELLM_LOCAL_MODEL_COST_MAP=True` stops LiteLLM fetching the model map on import.
- LiteLLM must stay `>=1.83.0`, because 1.82.7 and 1.82.8 were compromised on PyPI (March 2026).
- Importing litellm takes about 1.7s once per process.

## Leaderboard

- `Game.games_df()` calls `Game.leaderboard(count)`, which is `st.cache_data` keyed on the game count.
  It is recalculated only when a game is added.
- As of 2026-10-21 there are 7,579 games, and a recalculation takes about 2.4s:
  - TrueSkill about 1.8s. It is pure Python and sequential, and the scipy backend is about 10x slower.
  - Mongo fetch about 0.17s.
  - The groupby takes milliseconds.
- `Arena.rankings()` only shows models that are in `OPENROUTER_MODELS` and have at least
  `Arena.MINIMUM_GAMES` (10) games. Hidden models still count in everyone's TrueSkill ratings.
- Don't build the leaderboard with per-row DataFrame updates. That was the old `Result.update_on`, which took 20s.
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
  - that no temperature is sent
- `test_app.py` drives the app with `AppTest` and patches `dotenv.load_dotenv`, otherwise `.env` would bring
  back the real keys.
- `test_leaderboard.py` uses `use_database()`, which stubs `all`, `count` and `latest` and clears the
  leaderboard cache.
- Bugs get a failing test first, then the fix.
- A live check through OpenRouter costs money and needs the owner's approval.

## Conventions

- Docstrings use `:param x:` / `:return:`.
- No emojis in code or logs.
- Keep the README concise.
- Find the root cause, with evidence, before fixing anything.

## Status (October 2026 modernisation, uncommitted until the owner commits)

Done:
- Set up uv (`pyproject.toml`, `uv.lock`, `.python-version` 3.11), and moved Streamlit from 1.36 to 1.66.1 (README `sdk_version` too).
- Replaced the per-provider clients in `llms.py` with LiteLLM over OpenRouter, using structured outputs.
- Removed temperature everywhere.
- Renamed the prompt JSON keys to snake_case to match the schema.
- Replaced `use_container_width` with `width="stretch"`.
- Fixed these bugs, each with a regression test:
  - KeyError on a message to a non-player
  - message to yourself delivered back to you
  - give or take with yourself accepted (with a phantom alliance)
  - double save when a player goes bankrupt on turn 10
  - negative chart value after bankruptcy
- Leaderboard: 23s per click before, now about 2.4s after a new game and 0.06s on repeat clicks.
- The default lineup (`Arena.model_names`) is the owner's choice of four:
  - `openai/gpt-6-luna`
  - `anthropic/claude-haiku-5.5`
  - `deepseek/deepseek-v4.1-flash-1017`
  - `xiaomi/mimo-v2.6-flash`
- Reasoning effort is low, except DeepSeek and MiMo, which have reasoning off ("none"). Both reasoned far
  longer than the others at low.
- The live games below were played with a throwaway script that isn't in the repo. It loaded only the
  OpenRouter key, so the games weren't saved to Mongo. It recorded each raw response by wrapping
  `httpx.Client.send`.
- Live game 3 (2026-10-21, current settings): $0.026 and 106s. Every turn took 6-19s.
  - DeepSeek: 0 reasoning tokens, 2-8s a call, $0.006 a game instead of $0.023.
  - The slowest player is now MiMo, at up to 18s a call.
  - DeepSeek made the only invalid move. On turn 10 it gave to and took from the same player, after
    changing its mind partway through its strategy text. The schema can't forbid give == take, because
    strict JSON Schema has no constraint across two fields, so the referee rejects it (costing a coin).
- Live game 2 (2026-10-21, DeepSeek at "minimal", MiMo at "none"): $0.042 and 359s.
  - MiMo stopped reasoning (3-13s per call, $0.006 a game instead of $0.017).
  - DeepSeek hardly changed at "minimal": 1-14k reasoning tokens per call, 36s on average. It is now the
    only bottleneck, and its slowest call made the slowest turn (84s).
  - The per-call costs (`usage.cost` in each response and `/api/v1/generation`) agree. The key's total
    usage doesn't: it kept rising while nothing was being called, so something else uses that key too.
- Live game 1 (2026-10-21, everything at low): $0.054, which matched the key's usage. It took 1,000s.
  - All 40 calls succeeded and every move was valid, across 12 upstream providers. So the strict nested
    schema works for all four models.
  - Haiku 5.5 and Luna barely reason at low (0-265 reasoning tokens per call, 3-9s).
  - DeepSeek reasons 1.5-9k tokens per call and MiMo 0-17.5k, so they account for 76% of the cost and all
    of the wait.
  - Each turn waits for the slowest player. The worst call was MiMo on Xiaomi's own endpoint: 17.5k tokens
    at about 50 tok/s, 352s.
  - `require_parameters` doesn't enforce `reasoning`. Venice served MiMo without reasoning even though it
    doesn't list support for it.

Open:
- `grok-4` and `grok-4-fast` were dropped because they're not on OpenRouter. `grok-4.20-0309-reasoning`
  is mapped to `x-ai/grok-4.20`.
- The older models in `OPENROUTER_MODELS` haven't been tried live. Only the default four have.
- The HF build on Streamlit 1.66.1 is unproven until it's pushed.
- Leftovers: the old `venv/` folder and a local `alternate` branch.
