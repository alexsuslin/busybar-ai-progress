# Session dashboard implementation

The existing lifecycle queue remains the source of session status. One daemon per
device owns rendering and controls. No firmware changes or remote AI requests.

1. Add tests and a typed metadata adapter: model/provider/effort, actual context
   size and last usage, optional rate windows and reset times. Reject invalid
   numbers; never retain prompts or arbitrary strings. Claude status-line input
   writes only metadata locally. Codex daemon reads bounded local rollout tails
   for tracked session IDs; this supersedes the v0.1 design's no-transcript rule.
2. Add selection and visibility tests, then a controller with stable hashed IDs,
   priority-based initial selection, encoder wraparound, START press toggle,
   and manual hide/show/next/previous commands. Hidden stays hidden across events.
3. Render front status/icon/session/context and back model/effort/context/limits.
   Use native text/rectangles and fixed icon assets, avoiding repeated flash
   writes for token changes. Retry device failures with capped backoff. Subscribe
   to supported local status WebSocket using busylib; close resources on exit.
4. Add explicit --env-file loading, novice installation/run/troubleshooting docs,
   integration instructions for other projects and Claude, strengthened AGENTS,
   privacy notes, capability evidence, and release roadmap.
5. Run pytest, ruff check, ruff format --check, pyright; then smoke-test the actual
   API 27.5.0 device using .env without printing secrets. Inspect front/back output
   and exercise input delivery. State separately what lacks physical verification.

Key regressions to test: missing vs zero telemetry, cumulative-vs-current tokens,
model changes, expired limits, malformed/truncated input, per-session isolation,
no lifecycle changes from telemetry, release vs press, hidden refresh, reconnect,
ownership-safe clear, and fail-open hooks under invalid configuration.
