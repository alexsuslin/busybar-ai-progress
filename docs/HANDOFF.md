# Handoff

Current continuation point for busybar-ai-progress. Read [AGENTS.md](../AGENTS.md)
for workflow, privacy and hardware boundaries, [README](../README.md) for setup,
and [CONTRIBUTING](../CONTRIBUTING.md) for development and release checks.
Product follow-ups belong in [the roadmap](ROADMAP.md); research history remains
in [the design review](RESEARCH.md).

## Outcome and acceptance

- Current goal: pilot project-scaffolding 0.3.0 additive adoption in this repository.
- Acceptance: preserve existing guidance and application behavior; add a populated
  handoff, link it from AGENTS.md, and record provenance in .scaffold.json.
- Scope: documentation and provenance in busybar-ai-progress only. On 2026-11-11
  the owner authorized committing adoption and pushing the current branch. Other
  projects, merging to main, releases and live device changes are outside scope.
- Existing hooks, AI-client settings, daemon/tray processes, startup registration
  and devices are not installation or deployment targets of this adoption.

## Current state

- Last substantive update: 2026-11-11.
- Base revision: 66fd8ba9aca10c171674a156c20434ab4580dd13 on feat/windows-tray;
  one registered worktree, clean before adoption.
- Local main was bbf38e577ec66bb89aba2f3eee2128f99b396bb0 at inspection.
  No fetch was performed; remote branch, PR and CI status are not established here.
- Existing implementation: session lifecycle/status display, metadata rendering,
  Windows/WSL hook installation, and Windows tray controls with opt-in login startup.
  See the roadmap and changelog for details and limitations.
- Project version: 0.1.3.dev1; CHANGELOG.md lists 0.1.3 as unreleased.
  The base commit documents signed Python setup for Windows tray trust policies.
- Implemented in this working tree: docs/HANDOFF.md and .scaffold.json added;
  AGENTS.md keeps its existing rules and gains a link to this document.
- Delivery: prepared for the authorized commit and push to feat/windows-tray.
  Resolve the commit containing this handoff and check its remote branch / CI
  status for delivery evidence; this text precedes the push. Integration into
  main and release publication are not part of this task.
- Deployment / live observation: no hardware, emulator-service, real WSL, native
  tray or end-to-end AI-client checks are part of this adoption.

## Verification commands

Use the existing Python 3.13 environment and uv.lock. The local environment uses
signed Python 3.13.15; preserve Windows security policy. Run from the repository root:

- Tests: `uv run pytest -m "not emulator and not hardware"`.
- Lint: `uv run ruff check .`.
- Formatting: `uv run ruff format --check .`.
- Types: `uv run pyright`.

These gates come from AGENTS.md and CONTRIBUTING.md. Doctor infers pytest and Ruff
commands but does not discover the required Pyright gate or the integration-test
boundaries. Real WSL and native tray tests are also opt-in; do not enable them just
to make skipped checks pass. Use only synthetic fixtures in ordinary tests.
CI is configured for Windows and Ubuntu with Python 3.13, plus a history secret scan;
its configuration is not evidence of a successful remote run.

## Evidence

| Working state | Check / environment | Result |
| --- | --- | --- |
| Base revision | doctor and adopt --preview, scaffold 0.3.0 | Missing handoff; preview passed |
| Adoption working tree | pytest, Windows / Python 3.13.15 | 380 passed, 2 skipped, 4 deselected |
| Adoption working tree | Ruff lint / formatting | Passed; 51 files already formatted |
| Adoption working tree | Pyright | 0 errors, 0 warnings |
| Adoption working tree | doctor, scaffold 0.3.0 | Exit 0; only informational working_changes |
| Adoption working tree | Repeated adopt --preview | Already adopted; no additions proposed |
| Pre-commit adoption review | Diff / relative links / provenance | Only the three intended files; index and HEAD preserved before staging |

Checks ran on 2026-11-11 through `uv run --offline --no-sync` and the existing
Python environment. Test temporary data and the uv cache were isolated in a temporary
directory; pytest/Ruff caches and Python bytecode writes were disabled.
The two skips are real WSL interop and native Windows tray smoke tests. Four
hardware/emulator tests were excluded by marker. No hardware, emulator-service,
end-to-end AI-client, Linux, package-build or secret-scan result is claimed here.

## Remaining work

- Next action after the authorized push: review the adoption commit on the current
  branch and any reported CI results. A merge, release or product change requires
  its own task scope.
- Adoption does not configure Copier updates. Manifest hashes describe the original
  generated files; customizing this handoff does not require changing those hashes.
- Product and integration follow-ups remain in the roadmap. Keep simulated results,
  hardware observations and end-to-end client verification distinct.
- Who can continue: the owner or a session explicitly authorized for this project.
