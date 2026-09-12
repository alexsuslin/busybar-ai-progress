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

## Publishing a GitHub release

1. Run all four quality checks above and `uv build`. Ordinary tests use synthetic data;
   real WSL, emulator and hardware checks remain opt-in. State exactly which were run.
2. Inspect `git status --short` and the complete staged file list. Do not stage `.env`,
   local AI settings, logs, state, private keys or real session fixtures.
3. Install [Gitleaks](https://github.com/gitleaks/gitleaks) from an official release and
   verify its archive checksum. Run `gitleaks git . --log-opts=--all --redact=100
   --max-decode-depth 3` (on one line). Scan the proposed tree and extracted release
   artifacts too; history scanning alone does not inspect uncommitted files.
4. Inspect wheel and source archive manifests. Only release source, synthetic tests,
   documentation, scripts, placeholder configuration and licensed assets belong there.
   Smoke-test the built wheel in a clean environment from outside the checkout.
5. Update the version/changelog, commit the reviewed tree, tag it and push only the
   intended branch/tag. Wait for Windows, Linux and secret-scan CI to pass.
6. Attach the source ZIP, wheel, source distribution and SHA-256 checksums to the GitHub
   release. Never attach an entire working-directory ZIP or a scanner's raw findings.

CI pins action revisions, uses read-only permissions and scans full Git history with
redacted findings. It does not load AI account credentials or run real device tests.
