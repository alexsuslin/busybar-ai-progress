# Changelog

All notable changes to this project are documented in this file.

## 0.1.1 - 2026-09-12

- Translate the beginner README, research notes, roadmap and remaining planning prose into English.
- Require English for all project documentation and public GitHub release text in AGENTS.md.
- Publish English release notes and refreshed source archives; application behavior is unchanged.

## 0.1.0 - 2026-09-12

### Session dashboard

- Recover missing Codex Stop hooks from bounded local task lifecycle markers; reconcile
  tracked sessions every two seconds using the shared metadata reader. Preserve final
  questions, reject malformed/future markers, and avoid replaying old completion over new work.
- Cover differing hook/rollout turn IDs, truncation/gaps, and a synthetic missing-Stop
  scenario on the real BUSY Bar. `--no-telemetry` disables this local fallback too.

- START dismisses the selected session until fresh lifecycle activity; dismissals survive
  restarts, keep display numbers, and are excluded from dial navigation and display counts.
- Add local `dismiss` command and `status.sessions[].dismissed`; retain explicit hide/show.
- Prevent late tool completion from resuming a final-question or different-turn session;
  ongoing tool completions refresh activity and can reopen a dismissed running card.
- Make front/back context bars one pixel high and explicitly hide the old START/DIAL hint.

- Explain duplicate daemon launches explicitly instead of reporting generic OSError.

- Show model and reasoning on the front display alongside provider and session number.
- Automatically select active/recent sessions; retain manual dial selection for 30 seconds.
- Diagnose global versus project hook installation separately; require explicit client trust.

- Front/back dashboard with provider marks, model, effort, context usage and optional
  account rate windows; persistent readable session numbers (#01, #02) and selection with the BUSY Bar encoder.
- START press dismisses a session card through the local status WebSocket; RELEASE is ignored.
- Privacy-safe Claude status-line adapter and bounded local Codex metadata reader.
- Windows/WSL hook installation and removal preserving existing settings, shared state,
  and explicit compatibility documentation for CLI, VS Code and native Code sessions.
- Single-instance state lock, fail-open hooks under invalid configuration, sanitized
  queue rejection, timezone validation, bounded retry exponent and traceback-free errors.
- Russian installation guide, ecosystem research, firmware/API limitations and roadmap.
- Hardware regression for stale display elements; Windows/WSL invocation and WS tests.


### Initial lifecycle integration

- Add privacy-safe Codex lifecycle hooks and an atomic local event queue.
- Add concurrent-session state reduction with `QUESTION? > CODING... > DONE` precedence.
- Add deterministic 72×16 status artwork and BUSY Bar API rendering.
- Add bounded reconnect/priority backoff, CLI diagnostics, and manual state controls.
- Add emulator, direct USB, and BUSY Bar Manager development workflows.

### Release preparation

- Validate turn identifiers and restrict persisted reason codes to normalized lifecycle values.
- Keep malformed, excessively nested hook JSON fail-open without persisting raw input.

- Publish the first GitHub release with a source ZIP, source distribution, wheel and SHA-256 checksums.
- Exclude local AI settings, environment variants, keys, logs and build outputs from new commits;
  keep local hook files intact. Hook contract tests generate temporary settings.
- Define the source distribution contents explicitly and include third-party artwork notices in the wheel.
- Scan the Git history and release contents for secrets before publication.
