# Contributing

## Setup

```powershell
uv sync --python 3.13 --all-groups --link-mode copy
```

Use test-driven development for behavior changes: add a failing focused test, implement the
smallest change, then refactor with the test green.

## Quality gate

```powershell
uv run pytest -m "not emulator and not hardware"
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Emulator tests are opt-in:

```powershell
.\scripts\emulator.ps1 start
$env:BUSYBAR_EMULATOR_URL = 'http://127.0.0.1:8080'
uv run pytest -m emulator tests/integration/test_emulator.py -v
```

Hardware tests are also opt-in and never run in CI. Set `BUSYBAR_CODEX_ADDRESS` explicitly
before testing a physical device.

Regenerate the bundled status images with:

```powershell
uv run busybar-codex render-assets
git diff --exit-code
```

The second command must remain clean: generated images are deterministic.

## Privacy

Tests and fixtures may name sensitive input fields to verify redaction, but must never contain
real prompts, credentials, tokens, or authentication files. Hook code must remain bounded and
local: it records a normalized event and performs no network request.
