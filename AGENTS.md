# Project guidance

## Workflow and communication

- Use `request_user_input` for blocking questions when it is supported in the current
  mode. This lifecycle signal lets BUSY Bar show `QUESTION?`. Do not call unavailable
  tools or fabricate questions just to change the display. If unavailable, ask normally;
  final-message question detection is only a heuristic. Async question tools need their
  own explicit lifecycle adapter before being treated as authoritative signals.
- Implement behavior with test-driven development. Before claiming completion run:
  `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`.
  Report skipped integration tests and distinguish simulated, hardware and end-to-end
  AI-client checks. Keep user changes and do not reset their hooks/settings.
- Run ordinary tests offline from AI accounts. Use synthetic hook/rollout fixtures.
  Real hardware tests require `BUSYBAR_HARDWARE_TEST=1`; WSL tests require
  `BUSYBAR_TEST_WSL=<distribution>`. The user may authorize these in the conversation.

## Privacy boundary

- Never log or persist raw Codex/Claude hook stdin, prompt text, tool arguments,
  assistant messages, approval descriptions, access tokens or AI authentication files.
- Never print `.env`, environment dumps, private settings dumps or raw transcripts.
  Use `.env` in the process environment when hardware testing is authorized.
- Hooks/status-line handlers must only perform bounded local file writes. They must
  not contact BUSY Bar, OpenAI, Anthropic or any external service, start a daemon,
  install dependencies or read transcripts. Invalid data/configuration must fail open.
- Persist only normalized lifecycle IDs/state/time/reason and explicitly allowed
  metadata: persistent session display numbers/counter, model ID, effort, context size/percentage, rate windows/reset timestamps.
  Validate numbers (including huge integers/NaN/bools), text bounds and timestamps.
- The daemon may read bounded portions of local Codex rollout files for tracked session
  IDs. Keep raw records only transiently in memory; never copy them into a cache/log.
  Do not open auth.json, .credentials.json, browser cookies or account databases.
- Error logs contain fixed reason identifiers and exception class names only. Avoid
  traceback logging: chained transport exceptions may contain tokens in URLs.
  Invalid queue records must be replaced by a safe diagnostic, never quarantined raw.
- Installer changes preserve unrelated settings. Do not duplicate complete settings
  into backups: they can contain credentials. Uninstall only entries owned by this app.

## Architecture and compatibility

- `events.py` / `queue.py` / `state.py`: lifecycle normalization, local queue and reducer.
- `telemetry.py` / `local.py`: typed optional metadata, bounded reads, atomic writes/lock.
- `dashboard.py` / `rendering.py`: selection/visibility and front/back display elements.
- `busybar.py` / `inputs.py`: all device I/O, scoped ownership, WS decoding and retries.
- `install.py` / `cli.py`: installation, WSL interop and process orchestration.
- Maintain one display daemon per shared state directory. WSL hooks write through
  Windows interop to that directory; no HTTP hook relay and no competing WSL daemon.
- Missing data is unknown, never zero. Context means latest occupancy, not cumulative
  billing usage. Read actual model window and actual rate-window duration from source;
  never hardcode plan quotas or infer a supported provider for an unknown model.
- A skipped span of a rollout may contain a model change. Never join old model metadata
  across that gap and present it as current. Handle partial lines and truncation.
- BUSY Bar drawing upserts by element ID. Keep stable IDs, types and displays and
  explicitly hide stale elements. Clearing must name our application. Do not change
  priority/brightness/audio volume or flash firmware to work around an API failure.
- START dismisses the selected session on PRESS only; RELEASE must do nothing. Encoder
  delta selects non-dismissed sessions. A newer accepted lifecycle event reopens a card.
  Dismissal/hiding must never approve a tool request or stop an AI task.
- Physical controls also retain firmware behavior. Unsupported API/firmware changes
  belong in `docs/ROADMAP.md`, not speculative implementations.
- Verify current official APIs and inspect third-party licenses before adopting code
  or assets. Distinguish CLI, IDE extension, WSL and native Code from ordinary Chat.
- Update the Russian beginner README, compatibility matrix, security notes and changelog
  when changing installation, commands, stored fields or user-visible behavior.