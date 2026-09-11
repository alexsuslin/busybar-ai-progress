# BUSY Bar Codex Status

A small local daemon that reflects Codex activity on the 72×16 front display of a
[BUSY Bar](https://busy.bar/):

| Display | Meaning |
| --- | --- |
| `CODING...` | Codex is working |
| `QUESTION?` | Codex needs your input or approval |
| `DONE` | No active session needs attention |

Codex hooks only append privacy-safe local events. A separate daemon combines all active
sessions with the precedence `QUESTION? > CODING... > DONE` and talks to the device. Prompt
text, assistant messages, tool arguments, approval descriptions, and tokens are never stored.

## Requirements

- Windows 10/11 (primary supported platform)
- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and Git only for the optional emulator

Install the Python environment:

```powershell
uv sync --python 3.13 --all-groups --link-mode copy
uv run busybar-codex render-assets
```

The repository pins Python 3.13 in `.python-version`. The `copy` link mode avoids harmless
hardlink warnings when the uv cache and workspace are on different Windows filesystems.

## First run with the emulator

The [community BUSY Bar emulator](https://github.com/maxswinkels/busybar-emulator) is the
fastest development loop:

```powershell
.\scripts\emulator.ps1 install
.\scripts\emulator.ps1 start
```

Keep that terminal open and visit <http://127.0.0.1:8080>. In a second terminal:

```powershell
$env:BUSYBAR_CODEX_ADDRESS = 'http://127.0.0.1:8080'
uv run busybar-codex doctor
uv run busybar-codex run
```

The current emulator identifies its API as `25.0.0`, so newer busylib versions may print an
older-API warning. This is expected when `doctor` and the emulator integration tests pass.

Keep the daemon running. Restart/open Codex in this trusted repository, run `/hooks`, and
approve the project-local `.codex/hooks.json` if prompted. New Codex turns will then update
the display automatically.

For a manual smoke test while the daemon is running:

```powershell
uv run busybar-codex set coding
uv run busybar-codex set question
uv run busybar-codex set done
```

Run the emulator integration suite with the emulator still running:

```powershell
$env:BUSYBAR_EMULATOR_URL = 'http://127.0.0.1:8080'
uv run pytest -m emulator tests/integration/test_emulator.py -v
```

The emulator is unofficial and currently focuses on the front display. It is an excellent API
contract test, but it does not replace a final USB hardware smoke test.

## Use the physical BUSY Bar over USB

Connect the device by USB and use its default USB address:

```powershell
$env:BUSYBAR_CODEX_ADDRESS = 'http://10.0.4.20'
uv run busybar-codex doctor
uv run busybar-codex run
```

If `doctor` reports the device as unavailable, first check that Windows created the device's
USB network adapter and that <http://10.0.4.20/docs> opens. A token is normally unnecessary
over USB. For Wi-Fi, set `BUSYBAR_CODEX_TOKEN` if authentication is enabled.

The daemon uses application name `codex-status` and priority `50`. If another application
owns the display at a higher priority, it respects the resulting HTTP 409 and retries with
bounded exponential backoff; it never raises its own priority automatically.

## BUSY Bar Manager proxy

The app can also target the proxy from
[busybar-manager](https://github.com/maxswinkels/busybar-manager):

```powershell
$env:BUSYBAR_CODEX_ADDRESS = 'http://127.0.0.1:8321'
uv run busybar-codex doctor
uv run busybar-codex run
```

Manager is optional. Direct emulator and direct USB connections use the same application code.

## Configuration

CLI options `--address`, `--priority`, and `--config PATH` override the matching settings.
The most useful environment variables are:

| Variable | Default |
| --- | --- |
| `BUSYBAR_CODEX_ADDRESS` | `http://10.0.4.20` |
| `BUSYBAR_CODEX_APPLICATION_NAME` | `codex-status` |
| `BUSYBAR_CODEX_PRIORITY` | `50` |
| `BUSYBAR_CODEX_TOKEN` | unset |
| `BUSYBAR_CODEX_STALE_AFTER_SECONDS` | `86400` |
| `BUSYBAR_CODEX_LOG_LEVEL` | `INFO` |

An optional TOML file supports `address`, `application_name`, `token`, `priority`,
`stale_after_seconds`, `poll_interval_seconds`, `request_timeout_seconds`, and
`log_level`. Run `uv run busybar-codex doctor` to confirm writable local paths, hook
presence, the redacted target address, and API connectivity.

## Commands

```text
busybar-codex run
busybar-codex hook
busybar-codex status
busybar-codex set {coding,question,done}
busybar-codex doctor
busybar-codex render-assets
```

`hook` is intended for Codex and always fails open. Logs rotate at 1 MiB with three backups
and contain only state/reason identifiers and exception classes.

See [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and [SECURITY.md](SECURITY.md)
for the privacy and disclosure policy.
