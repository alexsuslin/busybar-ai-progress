# BUSY Bar Codex Status — Design

> Historical v0.1 design. The authorized session-dashboard extension in
> `../plans/2026-09-11-session-dashboard.md` supersedes the static-only display and
> no-rollout-metadata scope. The later activity update also supersedes the event mapping:
> permission evaluation shows CHECK; ordinary tools show TOOL; idle notifications and a
> question mark alone do not trigger ASK. Current behavior and privacy rules are in README
> and AGENTS.

## Summary

Build a Windows-first Python application that reflects the aggregate state of local Codex sessions on a BUSY Bar connected over USB. The front 72×16 RGB display shows one of three bundled images:

- `CODING...` while at least one Codex turn is active.
- `QUESTION?` while any Codex session needs user input or approval.
- `DONE` when no tracked session is active and no user response is required.

The application uses Codex lifecycle hooks as its stable input and the official BUSY Bar HTTP API through `busylib` as its output. It does not parse Codex transcript files, modify BUSY Bar firmware, or require an OpenAI API key.

## Scope

### Included

- Python 3.13 project managed with `uv`.
- A small hook receiver invoked by Codex lifecycle hooks.
- A long-running local daemon that owns communication with the BUSY Bar.
- Three deterministic 72×16 PNG assets bundled with the package.
- USB connection to `http://10.0.4.20` by default.
- Configurable device address, application name, display priority, retry policy, and stale-session timeout.
- Unit, contract, emulator, and hardware smoke tests.
- Windows documentation and commands; portable core code where practical.
- Public-project documentation and GitHub Actions CI.

### Excluded from the first release

- Custom BUSY Bar firmware or on-device JavaScript applications.
- Responding to Codex approvals from the BUSY Bar controls.
- Cloud control through `api.busy.app`.
- A native Windows tray GUI.
- Installing a Windows service or scheduled task automatically.
- Reading prompts, tool arguments, assistant text, or authentication tokens into application logs.

## Architecture

The system has four isolated parts:

1. **Hook adapter** — reads one Codex hook JSON object from standard input, reduces it to a privacy-safe local event, writes that event atomically to a queue directory, and exits quickly with status `0`.
2. **State reducer** — consumes queued events and maintains one state record per Codex session.
3. **BUSY Bar adapter** — uploads or verifies the bundled images and replaces the application's display element when the aggregate state changes.
4. **Daemon/CLI** — runs the event loop, retries device connections, exposes diagnostics, and supports manual state commands for testing.

Codex hooks never contact the hardware directly. This keeps device timeouts and USB disconnects out of the Codex critical path. Events are persisted as one-file-per-event using write-to-temporary-file plus `os.replace`, avoiding cross-process file locks and preserving events while the daemon is offline.

## Codex Event Mapping

| Codex event | Local transition |
| --- | --- |
| `UserPromptSubmit` | Session becomes `coding`. |
| `SessionStart` | Register the session; do not override a newer turn state. |
| `PermissionRequest` | Session becomes `question`. |
| `PreToolUse` for `request_user_input` | Session becomes `question`. |
| `PostToolUse` | If the session was `question`, it becomes `coding`; otherwise its state is unchanged. |
| `Stop` | Session becomes `done`, unless the last assistant message conservatively looks like a blocking question. |
| `Interrupt` | Session becomes `done` with an `interrupted` diagnostic reason. |
| `SessionEnd` | Remove the session from the active set. |

`Stop.last_assistant_message` is used only in memory for the fallback question check and is never persisted or logged. The fallback recognizes a final question mark and a small set of explicit request-for-input phrases. Project guidance will require Codex to use `request_user_input` for blocking questions when the tool is available; permission requests and structured user-input requests therefore remain the authoritative signals.

## Aggregate State

The daemon calculates one device state across all tracked sessions:

1. `question` if any non-stale session is waiting.
2. Otherwise `coding` if any non-stale session is active.
3. Otherwise `done`.

Each record contains only `session_id`, `turn_id`, normalized state, event timestamp, and an optional non-sensitive reason code. Active records older than the configurable timeout are pruned so a crashed Codex process cannot leave the display on `CODING...` forever. The default stale timeout is 24 hours to avoid misclassifying legitimate long-running work.

## BUSY Bar Integration

- Default address: `http://10.0.4.20`.
- Application name: `codex-status`.
- Display: front RGB panel, exactly 72×16 pixels.
- Assets: `coding.png`, `question.png`, and `done.png`.
- Assets are uploaded once per device/application version and reused by path.
- Draw calls replace only elements owned by `codex-status`.
- HTTP `409` priority conflicts are logged and retried with backoff; the application does not repeatedly raise its priority to defeat another display owner.
- API compatibility is checked at startup. Hardware runs should use strict compatibility after the device firmware is updated.
- USB requires no token. Future LAN support may read a token from environment or user config, never from committed files.

The daemon uses bounded request timeouts, exponential backoff with jitter, and last-state-wins rendering. If the device disconnects, the latest aggregate state remains in local storage and is rendered after reconnection.

## CLI

The package exposes `busybar-codex` with these initial commands:

- `busybar-codex run` — run the daemon in the foreground.
- `busybar-codex hook` — read one Codex hook event from standard input; intended for hook configuration.
- `busybar-codex status` — print aggregate state and device connectivity without prompt content.
- `busybar-codex set coding|question|done` — inject a manual test event.
- `busybar-codex doctor` — validate Python/package versions, state directories, hook configuration, and BUSY Bar reachability.
- `busybar-codex render-assets` — regenerate deterministic bundled status images.

Exit codes are stable: `0` success, `1` operational failure, `2` invalid configuration or input. The hook command is fail-open and returns `0` after recording a local diagnostic when possible, because display failures must not block Codex.

## Configuration and Local Data

Use `platformdirs` so Windows paths map to standard user locations and other operating systems remain supportable:

- Configuration: user config directory, `config.toml`.
- State: user state directory, session snapshot and queued events.
- Cache: user cache directory, generated/upload metadata.
- Logs: user log/state directory with rotation and no conversation content.

Environment variables override file settings for automation. At minimum: `BUSYBAR_CODEX_ADDRESS`, `BUSYBAR_CODEX_TOKEN`, and `BUSYBAR_CODEX_LOG_LEVEL`.

## Repository Layout

```text
busybar-ai-progress/
  .codex/
    hooks.json
  .github/
    workflows/ci.yml
  docs/
    superpowers/specs/
  src/busybar_codex/
    __init__.py
    cli.py
    config.py
    events.py
    state.py
    daemon.py
    busybar.py
    assets/
  tests/
    unit/
    contract/
    integration/
  AGENTS.md
  CHANGELOG.md
  CONTRIBUTING.md
  LICENSE
  README.md
  SECURITY.md
  pyproject.toml
  uv.lock
```

## Testing Strategy

### Unit tests

- Every event-to-session transition.
- Aggregate precedence: `question > coding > done`.
- Multiple concurrent sessions.
- Stale-session pruning with a fake clock.
- Atomic queue writes and recovery after partial temporary files.
- Retry/backoff and last-state-wins behavior.
- Asset dimensions, mode, and deterministic hashes.

### Hook contract tests

- Recorded minimal fixtures for each supported hook event.
- Unknown fields and unknown events are ignored safely.
- Malformed JSON never blocks Codex and never leaks raw input to logs.
- Blocking-question fallback does not persist assistant text.

### Emulator integration tests

- Run against the community BUSY Bar emulator at `127.0.0.1:8080`.
- Upload all assets, render each state, read back the screen, and validate expected dimensions/content.
- Exercise unreachable-device and HTTP `409` behavior.

### Hardware smoke tests

- Confirm `/api/version` over USB.
- Render all three states on current firmware.
- Disconnect and reconnect USB while the daemon runs.
- Verify another application's display ownership is respected.

Hardware tests are opt-in and never run in GitHub Actions.

## Quality Gates

Every implementation change must pass:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

CI runs on Windows and Linux for the pure Python and mocked-device suites. Windows is the primary supported runtime for the first release.

## Security and Privacy

- No OpenAI API key is needed.
- Never read or persist `~/.codex/auth.json`.
- Never persist prompt text, tool arguments, assistant messages, or approval descriptions.
- Treat LAN/cloud BUSY Bar tokens as secrets and redact them from errors.
- Project-local hooks require Codex trust review through `/hooks`.
- Hooks perform only bounded local writes and never control approval decisions.

## Operational Behavior

- The daemon starts in `done` when there is no fresh state.
- Duplicate events are idempotent.
- Rendering occurs only when the aggregate state changes or after reconnecting.
- Shutdown leaves the last rendered image on the device and writes a clean local snapshot.
- Unexpected exceptions are logged, then the daemon continues unless configuration is invalid.
- A disconnected BUSY Bar does not affect Codex or lose queued state transitions.

## Release Plan

The first usable release is `0.1.0` and is considered an MVP. It includes the foreground daemon, project-local hook configuration, three assets, diagnostics, emulator tests, hardware smoke-test instructions, and GitHub Actions. Native tray UI, autostart installation, LAN/cloud access, animations, and BUSY Bar input controls are deferred until the core lifecycle mapping is proven on physical hardware.
