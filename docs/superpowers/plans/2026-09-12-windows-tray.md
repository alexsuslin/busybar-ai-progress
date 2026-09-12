# Windows Tray Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent startup work and task/final review. Use TDD for behavior.

**Goal:** Run the BUSY Bar daemon from the Windows notification area with optional login startup.

**Architecture:** A thin pystray menu controls one cooperative daemon worker. A path-only launch profile supports pythonw and a single HKCU Run entry.

**Tech Stack:** Python 3.13, pystray, Pillow, winreg, python-dotenv.

**Spec:** [Windows tray design](../specs/2026-09-12-windows-tray-design.md)

## Global constraints

Preserve one daemon per state directory, hooks/settings, privacy boundaries and scoped device cleanup. No AI commands, new service, automatic startup by default, character or firmware changes. Windows-only GUI imports must remain lazy on Linux.

## Task 1: Startup registration

Files: `src/busybar_codex/startup.py`, `tests/unit/test_startup.py`.

Interface: `StartupRegistration(command: Sequence[str], store: RunStore | None = None)`, `enabled() -> bool`, `set_enabled(enabled: bool) -> None`; `RunStore.read() -> str | None`, `write(value: str) -> None`, `delete() -> None`. Registry adapter owns one exact HKCU Run value.

- [x] Write tests where enabling creates a quoted command, disabling removes only the exact owned value, a conflicting value is preserved, and >260-character commands are rejected before mutation.
- [x] Run `uv run pytest tests/unit/test_startup.py -q` and observe failure.
- [x] Implement registry boundary with `subprocess.list2cmdline`, lazy winreg and injected store.
- [x] Run focused tests, Ruff and Pyright; review independently.

## Task 2: Tray worker and cooperative daemon lifecycle

Files: `src/busybar_codex/tray_runtime.py`, `src/busybar_codex/cli.py`, `src/busybar_codex/daemon.py`, `tests/unit/test_tray_runtime.py`.

Interface: `TrayController(runner: Callable[[Event, Callable[[], None]], None], controls: ControlInbox)` with `start`, `stop`, `restart`, `close`, `status`, `control`; runner calls `run_daemon(..., stop_event=event, on_ready=ready)`.

- [x] Test real worker Events: duplicate start rejected; Stop releases runner; Restart starts only after old runner completes; Exit prevents restart; errors expose only fixed codes; controls persist only existing actions.
- [x] Observe RED using focused pytest.
- [x] Extend `run_daemon` with optional cooperative Event; implement serialized worker management and sanitized status.
- [x] Verify stop reaches daemon and releases the real instance lock; run focused tests.

## Task 3: Windowless launcher and native menu

Files: `src/busybar_codex/tray_launch.py`, `src/busybar_codex/tray.py`, CLI/pyproject/uv.lock, launcher/menu tests.

- [x] Test absolute path profile roundtrip, size/type validation, filtered non-interpolated env loading, no persisted token, pythonw launch with redirected standard streams, unsupported platforms, and menu actions through controller.
- [x] Observe RED; implement path-only profiles, GUI entry point, launch subprocess and native menu with pystray imported only at runtime.
- [x] Add separate tray lock, async UI refresh and cooperative Exit cleanup. Handle duplicate startup and errors with fixed messages.
- [x] Inspect dependency licenses and verify Windows icon/menu manually with synthetic/local smoke checks.

## Task 4: Documentation and final verification

Files: README compatibility/commands, SECURITY, CHANGELOG, ROADMAP, THIRD_PARTY_NOTICES.

- [x] Document launch, startup on/off, fixed paths, secret handling, shutdown and limitations in English.
- [x] Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, build and review final diff.
- [x] Fix material review findings; report test scope and how to start/use the tray. Do not publish the unfinished tray in 0.1.2.

## Decisions

Work on `feat/windows-tray` in the current checkout after publishing the clean release snapshot. The user requested continued implementation; retain the current workspace for their installed hooks and environment. No extra checkout or settings copy is needed.

Ruling: delay Running/controls until the daemon confirms its instance lock via on_ready. Review found that optimistic status could send controls to an existing daemon.

Ruling: scope profile filenames by state-directory hash, keep manual launch available when startup paths are too long, catch registry errors in menu checks, and close the worker after native refresh errors. Each review finding has a synthetic regression test.

Validation: 380 tests passed with six opt-in checks skipped; the native Windows tray test was then run separately and passed. Ruff and Pyright passed. Full Windows sign-in, physical device interaction and end-to-end AI-client checks are not part of this tray test run.

Local rollout: actual pythonw launch was blocked by Windows Application Control (4551). The native menu passed with a synthetic worker, but windowless startup and real login remain unverified on this machine. No security policy changes or interpreter bypass were attempted. The tray branch was committed locally; automatic approval review rejected publishing the new branch, so only the earlier 0.1.2 release is public.
