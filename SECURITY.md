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

## Activity phases and effort capability metadata

PermissionRequest is an evaluation stage, not proof that a person sees an approval dialog:
auto-review or another hook can decide it. It produces CHECK, not ASK. Exact blocking question
tools and permission notifications can produce ASK; explicit input-request phrases in final
messages remain a best-effort heuristic. Idle notifications and punctuation alone are ignored. No display action approves or rejects a request. THINK denotes the phase
between reported tools; it can include model or transport latency and does not expose reasoning.
TOOL and COMPACT come from lifecycle hook types. Only fixed normalized reasons are stored,
never tool names, arguments, results or reasoning content.

The daemon may read `models_cache.json` beside a configured Codex sessions directory, with a
2 MiB limit, at most 256 models and eight strictly ordered effort levels per model. Only exact
model IDs and validated effort labels survive in memory. Catalog instructions, descriptions
and other fields are not retained. The optional `effort_levels` metadata field contains only
these labels. Missing catalogs, unknown models, mismatched current effort or malformed data
hide the scale; none are interpreted as zero. Hooks never read model catalogs or open network
connections. The cache schema is an internal, best-effort source and may change.


## Display freshness

`usage_observed_at` is a validated, transient in-memory timestamp only. It is excluded
from metadata files and the `status` JSON projection. Codex supplies it from the
bounded usage record already read by the daemon; Claude uses the metadata file's
receipt modification time after a bounded, consistency-checked read. No new files,
account access, hook network calls, or persisted fields are introduced. Model hints,
lifecycle events and unrelated rollout writes cannot refresh the usage timestamp.
Missing, invalid or future timestamps yield unknown age. Restoring/copying Claude
metadata can change its apparent receipt time; it is not an authenticated provider
measurement. Stale usage changes presentation only, never lifecycle, permissions,
dismissals or task execution. Reset countdowns use supplied timestamps and actual
window durations; passing a reset clears the old window instead of inventing capacity.


## Status motion and session overview

Motion phase, completion timing, overview pages and selected pointers exist only
in memory. Overview cells reuse already permitted display numbers and lifecycle
states; they contain no project names, prompts or messages. Animation does not
read transcripts, infer AI connection health, or change lifecycle state. A steady
ASK label still requires an authoritative input signal or the documented fallback.

The daemon schedules motion using a monotonic clock, sends motion-only updates at
most twice per second, retains full refresh/retry rules, and stops motion while
hidden. Completion acknowledgement is limited to a visible selected transition;
opening an old completed session does not replay it. START/encoder behavior and
firmware ownership remain unchanged. Disabling status motion changes presentation
only. The implementation uses existing rectangle/text upserts, with stable element
IDs and explicit hiding, not native undocumented animation formats or new assets.
