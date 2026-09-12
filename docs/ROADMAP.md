# Upcoming releases

## Already implemented

Session statuses and numbers, provider icons, model/effort, context occupancy,
available limits, two displays, dismissing the selected session with START and switching
sessions with the encoder. Newer accepted lifecycle activity reopens a dismissed card.
The Windows/WSL hook installer preserves other settings.
These features use existing HTTP and WebSocket interfaces without firmware changes.

## Priority 1 — easier everyday use

1. **Windows tray and automatic startup.** Actions for Start, Hide, Restart and
   Check connection, plus device selection and a log of safe error codes.
   Add a signed installer and a supported way to remove automatic startup.
2. **Setup wizard.** Detect installed CLI/VS Code/WSL clients and show separate
   results: hook installed, trusted by the client, event received, metadata received.
   The installer currently adds entries but cannot establish trust on the user's behalf.
3. **Automatic selection settings.** Priority-based selection and manual pinning
   for 30 seconds already work. Add a configurable duration and a new-question
   indicator that remains visible while another session is selected manually.
4. **Data age and waiting time.** Show the time since the last update and how long
   a session has been waiting for an answer. Distinguish missing data from stale data.
5. **Easy cleanup of synthetic/stuck sessions and bounded retention.** Add
   `forget`/`prune`, a queue size limit, cleanup of old metadata/diagnostics
   and recovery from a corrupt snapshot. Keep hooks short.

## Priority 2 — more useful information

- Time until limits reset and warnings at 80/95%, with configurable thresholds.
- A quiet, short sound for QUESTION only; a separate setting for DONE and a night mode.
- Compare multiple sessions on the back display; optional user-supplied short names
  instead of numbers, without automatically showing project names or prompt text.
- Automatically cycle through status/model/limits on the front display when the back is hidden.
- An office privacy mode: color/icon only, without the model or ID.
- Connection status and display recovery after a crash, using verified element TTL
  behavior. A clean shutdown currently clears the display; forced termination may
  leave the last image visible.
- BUSY Bar Manager integration with checks for WebSocket support and display ownership.

## AI application compatibility

### Graphical Claude Code clients

Hooks work where the client reads the settings. Full context/limit information
requires an explicitly supported telemetry channel from the graphical client. The
next step is to check running versions of VS Code/Desktop for such a channel and
add a separate adapter with contract tests. Do not patch the installed extension or
read OAuth credentials to access an unofficial endpoint. Use statusLine data only
when the client actually invokes it.

### Codex without hooks and remote sessions

A possible read-only adapter could use app-server events or local lifecycle records,
as some related GitHub projects do. It would need version checks, a way to distinguish
an active session from an old unfinished file, and protection against duplicate events
and conflicts with hooks. For SSH/cloud sessions, use a separate process that forwards
only normalized events; the hook itself must not access the network. Automatic support
is not currently claimed.

### Ordinary ChatGPT / Claude Chat / Cowork

These are separate processes from Codex/Claude Code. This project has not confirmed
a universal public source for their lifecycle, actual context occupancy and quotas.
A supported API/extension from the application is needed. OCR, screen observation
and interception of private traffic are not reliable substitutes. BUSY Bar firmware
does not remove this limitation.

## Requires BUSY Bar API or firmware extensions

- **Exclusive buttons/encoder for the widget.** The WebSocket currently reports
  actions but does not cancel the built-in handler. A control-capture API is needed,
  with an application ID, TTL and automatic release when the connection is lost.
- **Reliable on-device widget lifecycle.** Dedicated close, restart and display
  ownership change events would allow the UI to recover correctly without periodic
  redrawing.
- **Operation without a computer.** This requires an app on the device itself and
  a supported status source. It is a separate architecture, rather than a hook enhancement.

Buttons for approving AI permissions, changing reasoning settings and sending text
are not implemented: they require a stable API that addresses a specific AI session.
Hiding a status must never be interpreted as permission to perform an action.
