# Security and privacy

Hooks accept Codex/Claude lifecycle JSON in memory and write only session/turn IDs,
normalized state, timestamp and a fixed reason code. Claude statusLine and model hints
write only validated model ID, effort, context size/percentage and rate windows/reset
timestamps. They never contact the device or AI services. Raw stdin is never logged. Session and turn IDs are restricted to 1–128 ASCII
identifier characters; persisted reasons must belong to the fixed lifecycle allowlist.
Malformed or excessively nested hook JSON is ignored without interrupting the AI client.

The daemon reads bounded local Codex rollout data only for tracked sessions and extracts
model/effort, token-count metadata, and normalized task_started/task_complete/turn_aborted
lifecycle markers (session/turn IDs, timestamp, state, fixed reason). The shared reader
uses the same bounded read for both, only for tracked sessions, and caches no raw rows.
A latest-turn start/completion pair is retained transiently; only normalized reducer
state is persisted. Missing/malformed/partial records and skipped spans are not joined
with old lifecycle data to infer current activity. It never copies raw transcript records or opens
Codex/Claude authentication files. Unsupported or missing fields remain unknown.
`run --no-telemetry` disables both metadata and lifecycle rollout reading by the daemon.

Display/WS I/O belongs to the daemon. Device tokens are held in configuration/environment
and passed only to the configured BUSY Bar endpoint. `.env` is Git-ignored. Do not enable
third-party HTTP/WebSocket debug logging: request URLs or exceptions can contain tokens.
Application error logs contain fixed codes and exception classes, without tracebacks.

WSL uses Windows executable interop and shared local files, not an HTTP hook endpoint.
Only the Windows daemon talks to the device. Keep the state directory private to your
OS account; local processes with write access can forge statuses and control the widget.
Hiding the widget or dismissing a session card never approves AI requests, stops AI
work or changes permissions. START dismisses only the selected card; dismissal persists
as a session-ID-to-lifecycle-timestamp map (`dismissed`) in the snapshot, validated
against existing records. Only a newer accepted lifecycle event reopens the card;
metadata refreshes and repeated registration do not. The `status` command exposes a
boolean `dismissed` for each tracked session, including those absent from the display.

The installer preserves other settings and existing statusLine commands. It deliberately
does not back up entire settings files, which might contain credentials. Uninstall removes
only identified app-owned entries. Review and trust hooks in the AI client itself.

Logs rotate at 1 MiB with three backups. Session records expire after the configured
stale interval; metadata files, queue diagnostics and interrupted temporary files may
remain on disk. Automated disk-retention cleanup is a documented future improvement.
Malformed committed queue files are replaced with a safe reason code, not retained raw.

Do not commit private configuration, state, caches, logs, emulator checkouts or credentials.
See THIRD_PARTY_NOTICES.md for artwork provenance.

## Reporting a vulnerability

Report vulnerabilities privately to the repository owner. Include a minimal synthetic
reproduction, application/API versions and the affected launch environment. Do not
include tokens, prompts, transcript excerpts, hook stdin or private configuration files.
Installed Python commands use isolated mode (`-I`) to prevent import shadowing by the
active project or `PYTHONPATH`. A sibling `.busybar-statusline.json` receipt stores
only our installed status-line command, never a copy of user settings. Reinstall
and uninstall use exact receipt matching to preserve user replacements.

The daemon snapshot also stores sequential session display numbers and their next
counter. These reveal no project names or message content.

## Release boundary

Local `.env` variants (except the placeholder-only `.env.example`), `.codex/`, `.claude/`,
keys, logs and build outputs are ignored. Existing local hooks are left on disk; installation
creates paths for each user's machine. Source packages use an explicit inclusion list, and
release archives are inspected and scanned together with the full Git history before upload.
Automated secret scanning reduces risk but cannot prove that arbitrary text contains no secrets.
Never use `git add -f` to publish private files. See CONTRIBUTING.md for release checks.
