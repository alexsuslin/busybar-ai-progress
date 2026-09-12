# BUSY Bar — Claude Code and Codex status

This app shows whether your AI assistant is working or waiting for your reply,
and which session is selected, on your BUSY Bar. It runs on your computer;
you do not need a separate OpenAI or Anthropic API key.

The **front display** shows the OpenAI/Anthropic icon, model, a short session number
(`#01`, `#02`), `RUN`, `ASK`, or `DONE` status, reasoning effort, and a context usage
bar along the bottom. Long model names scroll; the provider icon stays on the left.
The **rear display** shows the model name, reasoning effort, session, session and
question counts, context usage, and available usage limits. Long names scroll.
Icons come from Simple Icons; see the [licenses](THIRD_PARTY_NOTICES.md).

The **large START button on top** dismisses the selected session card.
The next undismissed card appears; once every card is dismissed, the widget disappears.
The **dial** cycles through undismissed cards only. A dismissed session returns with
its original number only after a new working, question, or completion event.
Re-registration, old events, and metadata updates do not reopen it.
Dismissal survives an app restart. It does not stop the AI, answer questions, or
grant permissions. The rear display no longer has a START/DIAL hint;
the context bars on both displays are one pixel high.

The `dismiss` command does the same thing as START. The `hide` and `show` commands
separately hide and show the entire widget: after `hide`, new events do not bring it
back until `show`. `show` does not reopen dismissed cards. Restarting the app clears
this overall hidden state, but dismissed cards stay dismissed.
The button also retains its normal firmware action: this app does not take exclusive
control of it. We recommend setting the switch to **APPS** to avoid also controlling
the timer.

## Supported clients

| Where the assistant runs | Session status | Model, reasoning effort, context, usage limits |
| --- | --- | --- |
| Codex CLI in PowerShell / the VS Code terminal | Hooks + reconciliation with local turn start/end markers; START dismisses the card | From local session files, when fields are available |
| Codex VS Code extension, local session | Hooks + local markers for sessions already registered | From local files belonging to the same user |
| Native Codex app, local session | Hooks + local markers for sessions already registered | From local session files |
| Claude Code CLI, including `claude.exe` and the VS Code terminal | Through Claude hooks; START dismisses the card | Through `statusLine` |
| Claude Code VS Code extension | Through shared hook settings | Model from the hook, if provided; other fields only if the client calls `statusLine` |
| Claude Desktop, **Code** tab, Local environment | Through shared hook settings | The same limitation applies: hooks do not guarantee all metadata fields |
| Claude Code / Codex in WSL, including VS Code Remote WSL | Through the WSL bridge to Windows | Claude: `statusLine`; Codex: reading the WSL sessions directory |
| Ordinary Claude Desktop / ChatGPT Desktop chats, Cowork, browser and cloud sessions | Not connected by this adapter | No universal source for these data; see the [roadmap](docs/ROADMAP.md) |

A terminal inside VS Code and a graphical extension are different ways to run an
assistant. Not all graphical clients call the terminal `statusLine`.
Hook support in Claude VS Code and local Code is documented in the official
[VS Code documentation](https://code.claude.com/docs/en/vs-code)
and [Desktop documentation](https://code.claude.com/docs/en/desktop#shared-configuration).
Codex events come from [official hooks](https://learn.chatgpt.com/docs/hooks).

**What has been verified in this project:** automated tests, execution of generated
Windows hooks, the bridge through a real Ubuntu/WSL installation, HTTP drawing on
BUSY Bar with API 27.5.0, and reading both displays. WebSocket connections have been
tested on the device; button/dial event conversion has been tested against a test
server using real protobuf packets. A complete manual check of every GUI client
and separate verification of physical button presses have not been performed.

## Windows installation, step by step

### 1. Prepare your BUSY Bar

Connect it with a USB cable that supports data transfer. Open
<http://10.0.4.20> in your browser. If the device page loads, the connection works.
This is the network address of the USB connection; it does not need internet access.

You can also use Wi-Fi: your computer and BUSY Bar must be able to reach each other
on the network. Enable HTTP API access in BUSY Bar settings and find its address.
Buttons do not work through a cloud address: their WebSocket is available locally.

### 2. Install uv

`uv` is a tool that downloads the required Python version and libraries for you.
Open the Start menu, search for **PowerShell**, and paste this command:

```powershell
winget install --id astral-sh.uv -e
```

Close PowerShell, open it again, and check:

```powershell
uv --version
```

If `winget` is unavailable, use [another official uv installation method](https://docs.astral.sh/uv/getting-started/installation/).
You do not need to install Python, Node.js, or Git separately for normal use.

### 3. Download the project and install its libraries

Open [release v0.1.1](https://github.com/alexsuslin/busybar-ai-progress/releases/tag/v0.1.1)
and download `busybar-ai-progress-v0.1.1.zip` under **Assets**. Extract the archive
to a permanent folder, such as `D:\work\busybar-ai-progress`. Do not run the project
from inside the archive. Open the extracted folder in File Explorer, type
`powershell` in the address bar, and press Enter. Enter all the following commands
in that window.

```powershell
uv sync --python 3.13 --all-groups --link-mode copy
```

The first run needs internet access and may take a few minutes. Wait for the
PowerShell prompt to return. You do not need to activate the virtual environment
manually.

### 4. Configure the connection

If `.env` already exists, open that file and keep the values you need.
If it does not exist yet:

```powershell
Copy-Item .env.example .env
notepad .env
```

For USB, this line is enough:

```dotenv
BUSYBAR_CODEX_ADDRESS=http://10.0.4.20
```

For Wi-Fi, replace the address with your BUSY Bar address. If the device requires
an access code, add `BUSYBAR_CODEX_TOKEN=your_code`. This is the **BUSY Bar** code,
not a Claude/OpenAI token. Do not publish `.env`, share its contents in messages,
or commit it to Git. Make sure Notepad saves it as `.env`, not `.env.txt`.

Check the connection:

```powershell
uv run --env-file .env busybar-codex doctor
```

A successful result includes `device: ok (API ...)`. The access code itself is
not printed. The `uv --env-file` option loads `.env`; plain `uv run` does not load
it automatically. The display process needs the address/token; hooks do not
connect to the device.

### 5. Connect your AI assistants

Install whichever integration you need, or both:

```powershell
uv run busybar-codex install-hooks --client codex
uv run busybar-codex install-hooks --client claude
```

These commands add entries to your user settings: `~/.codex/hooks.json` for Codex
and `~/.claude/settings.json` for Claude. `~` means your Windows home folder.
Existing hooks, permissions, plugins, and status lines are preserved.
Running the installer again does not duplicate this app's entries. The installer
does not bypass the client's hook trust settings or change AI permissions.

If you see `statusline: existing command preserved`, you already have a custom
Claude status line. It has been preserved. Session statuses work, but complete
metadata may be unavailable. To connect it, you must deliberately combine the
scripts or remove your own `statusLine` and run the installer again. The installer
does not automatically run someone else's script or replace your status line.

Fully restart Codex / Claude / VS Code. In the CLI, open `/hooks`, check the new
handlers, and confirm trust if the client asks. Start a **new session**.
A session that was already running may not pick up the new hooks.

For graphical Claude, use the **Code** tab with **Local** selected.
For VS Code, run the installer on the machine where the assistant actually runs:
Windows for local sessions, or follow the next section for Remote WSL.

Invalid hook data is skipped: session and turn IDs have format and length limits,
and the original JSON is never saved or printed.

Local `.codex/hooks.json` and `.claude/` files are not included in the release.
Install hooks with the commands above to create settings with paths for your own
computer. If your working project already has its own hooks, both global and
project handlers may fire, causing extra invocations. Existing local settings
are preserved.

### 6. Start the display process

```powershell
uv run --env-file .env busybar-codex run
```

Leave this window open. It is normal for no new lines to appear: the app is waiting
for events. Start a task in your AI assistant; the status should change.
A second process using the same state directory will not start. Press **Ctrl+C**
to stop. On normal shutdown, the app clears its own widget. If the process is
forcibly terminated, the last image may remain until the next start or clear.

For a simpler launch after installation, open PowerShell in the project folder
and run:

```powershell
.\scripts\start.ps1
```

If Windows policy blocks `.ps1` files, use the regular `uv run` command above;
you do not need to change system policy. Automatic startup at Windows sign-in
is not installed yet.

## WSL and VS Code Remote WSL

The main display process continues to run **in Windows**. WSL does not need a
second instance, another Python installation, or a separate HTTP server.
The Linux hook calls the already installed Windows Python and writes a normalized
event to the shared directory. This uses WSL's standard ability to run `.exe` files.

In **Windows PowerShell**, from the project folder:

```powershell
wsl --list --quiet
uv run busybar-codex install-hooks --client claude --wsl-distro Ubuntu
uv run busybar-codex install-hooks --client codex --wsl-distro Ubuntu
```

Replace `Ubuntu` with the name shown by the first command. Repeat for other
distributions if you use several. The installer finds the Linux home folder,
adds hooks there, and registers the Codex sessions directory for the Windows
daemon to read. Restart the daemon and AI sessions. The same hooks serve the
WSL terminal and extensions running in a **VS Code Remote WSL** window.

Do not move the project folder after installation: hooks contain the path to its
Python executable. If you need to move it, reinstall hooks from the new folder.
Next to Claude settings, the installer saves `settings.json.busybar-statusline.json`.
It contains only this app's status line command. The installer uses it to update
an old path when you reinstall, while preserving your own status line.
Do not delete this file before uninstalling the integration.
The bridge does not work if WSL interop is disabled. If you use a custom
`CODEX_HOME` / `CLAUDE_CONFIG_DIR` in WSL, use `--target` for the actual settings
file and add the actual Codex directory with `run --codex-sessions-dir`.

## Reading the display

On the front display, the provider icon is on the left and the model name is at
the top. A bottom line such as `#03 RUN HIGH` means session 3, assistant working,
high reasoning effort. If the client has not provided a model yet, the top line
shows the status; the icon appears once the model arrives. `N/A` on the bottom
line means unknown reasoning effort. Codex model and reasoning information
usually appear after the first request.

| Label | Meaning |
| --- | --- |
| `RUN` on the front / `CODING` on the rear | The assistant is working on the current request |
| `ASK` on the front / `QUESTION?` on the rear | A reply or permission is needed; respond in the AI app |
| `DONE` | The selected session has finished the current request |
| `REASONING high` | The configured reasoning effort, not the text of internal thoughts |
| `CTX 25% / 200,000` | The latest known context occupies a quarter of a 200,000-token window |
| `USED 5h 23% 7d 41%` | 23% of the short usage limit and 41% of the weekly limit have been used |
| `N/A` | The client has not provided usable data; it does not mean zero |
| `SESSIONS 3 QUESTIONS 1` | One of three known sessions is waiting for your reply |

The bar shows **context usage**, not task completion progress. The total tokens
used throughout a session are not treated as current window occupancy.
The window size comes from client data, not a model lookup table: the same model
can run with different context sizes. After compaction (compression of conversation
history), the bar may shrink.

Automatic selection prioritizes questions, then work, then completion. If statuses
match, the session with the newest event is shown. Turning the dial keeps your
manual selection for 30 seconds, then automatic selection resumes. Dismissed cards
are excluded from automatic selection. Also check the question count on the rear
display. `status` lists all sessions with the same numbers; `dismissed: true` means
a dismissed card. Counts on the device include only undismissed cards.
A session receives its number when it first appears. The number survives app
restarts and does not change when neighboring sessions are dismissed. The dial
cycles through sessions in number order. A number is never reassigned to another
session after completion or removal of a stale session; if a removed session
reappears, it receives a new number. You can dismiss completed cards with START.
Session records are removed on SessionEnd or after 24 hours without events;
once removed, their previous numbers are not retained.
`RUN` reflects the last received working event; it is not a check of the AI process.
For registered Codex sessions, the daemon reconciles local `task_started` /
`task_complete` / `turn_aborted` markers every two seconds, recovering a missed
Stop from the turn completion. It reads only allowed lifecycle fields within
the same bounded reads used for metadata. A new start restores RUN; old events
do not override newer hooks, and the current turn's final question is preserved.
The local file format is a best-effort source, not a stable public API.
Without usable markers, with `--no-telemetry`, or with Claude, a missed Stop can
still leave an old status until the next event or expiry. A late PostToolUse after
a final question or completion, or from another known turn ID, does not restore `RUN`.

Usage limits appear only when the client provides them. For Codex, the window
duration comes from the event: it may be 1h, 5h, 7d, and so on. Claude uses
[`statusLine` fields](https://code.claude.com/docs/en/statusline#available-data).
A missing subscription limit is not replaced with an API requests-per-minute limit.
After the reset time, the old percentage is hidden until new data arrives.
Known percentages are the client's latest snapshot; the app does not request
them separately from the provider.

## Check without sending an AI request

While `run` is running, open a second PowerShell window in the project folder:

```powershell
uv run busybar-codex set coding --session demo-one
uv run busybar-codex set question --session demo-two
uv run busybar-codex next
uv run busybar-codex previous
uv run busybar-codex dismiss
uv run busybar-codex hide
uv run busybar-codex show
uv run --env-file .env busybar-codex status
uv run busybar-codex set done --session demo-one
uv run busybar-codex set done --session demo-two
```

Synthetic sessions have no model or limits, so `N/A` is expected. The
`set`/`dismiss`/`hide`/`show` commands enqueue events; the display will not change
unless `run` is running.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| `uv` not found | Restart PowerShell after installing uv |
| `device: unavailable` | Check the cable/address, open the BUSY Bar page in a browser, and run `doctor` again |
| Wi-Fi requires authentication | Check the BUSY Bar code in `.env` and the `--env-file .env` flag |
| A timer/another app occupies the screen | Stop it or switch to APPS; this app respects priority and retries |
| AI activity does not change anything | Check that `run` is running, hooks are trusted, and the session was created after installation |
| WSL works, but BUSY Bar shows nothing | Check the distribution name and access to Windows `.exe` files; restart the daemon after installing WSL hooks |
| A new session in another folder does not appear | Install global hooks with `install-hooks --client codex`, allow the BUSY Bar entries in `/hooks`, and restart Codex / the VS Code window; `doctor` reports global and project files separately |
| Status appears, but model/context shows `N/A` | Check your client in the support table; a GUI may not call statusLine, and the Codex format may change |
| Buttons do not work through a proxy | The proxy must forward WebSocket `/api/status/ws`; try the direct USB/Wi-Fi address |
| `BUSY Bar is already running...` | The app is already running for this state directory. Use that instance or stop it with `Ctrl+C` in its terminal before starting another |
| `operational failure: OSError` | Check access to settings and state directories; this is a separate filesystem error |
| `invalid configuration or state` | Check numbers/JSON/TOML; if state is damaged, stop the daemon and rename `sessions.json` in the state directory |
| Old sessions clutter the display | Select a card with the dial and press START; repeat for other cards. A card returns on new activity |
| The image remains after closing the window | Start the daemon again and run `hide`; use Ctrl+C for a clean shutdown |

Logs contain only technical reason codes and exception class names. Do not enable
HTTP/WS debug logs for a bug report: a third-party library may print an address
containing the access code. Include the app version, API version, client type
(CLI/VS Code/WSL/Desktop), and check result, without `.env` contents or conversation
history.

## Settings and files

Precedence: app arguments → environment variables → TOML → defaults.
Global arguments go **before** the command: `busybar-codex --address ... run`.
The uv `--env-file` flag goes **before** `busybar-codex`.

| Variable | Default |
| --- | --- |
| `BUSYBAR_CODEX_ADDRESS` | `http://10.0.4.20` |
| `BUSYBAR_CODEX_TOKEN` | Unset |
| `BUSYBAR_CODEX_APPLICATION_NAME` | `codex-status` |
| `BUSYBAR_CODEX_PRIORITY` | `50` (1–100) |
| `BUSYBAR_CODEX_STALE_AFTER_SECONDS` | `86400` |
| `BUSYBAR_CODEX_POLL_INTERVAL_SECONDS` | `0.2` |
| `BUSYBAR_CODEX_REQUEST_TIMEOUT_SECONDS` | `2` |
| `BUSYBAR_CODEX_LOG_LEVEL` | `INFO` |
| `BUSYBAR_CODEX_STATE_DIR` | App directory in the user profile |

Use `--state-dir` to set the shared directory explicitly. If you change it,
reinstall hooks with the same `--state-dir`, or events will go to a different place.
`BUSYBAR_CODEX_CONFIG_DIR`, `BUSYBAR_CODEX_CACHE_DIR`, and `BUSYBAR_CODEX_LOG_DIR`
let you move the other directories. To view their paths without secrets:

```powershell
uv run python -c "from busybar_codex.config import Config; c=Config.load(); print('state:', c.state_dir); print('logs:', c.log_dir); print('config:', c.config_dir)"
```

The state directory contains the queue, `sessions.json` (including session numbers
and `dismissed`: dismissed session ID → time of its latest event), safe Claude
metadata, control commands, a lock file, and registered Codex WSL directories.
You can leave the lock file in place: the operating system releases the lock when
the process exits. Specify a TOML file with `--config PATH`; its keys correspond
to the settings `address`, `application_name`, `token`, `priority`,
`stale_after_seconds`, `poll_interval_seconds`, `request_timeout_seconds`, and `log_level`.

The `run` command supports `--no-input` (disable buttons), `--no-telemetry` (hooks
only, without reading metadata or lifecycle events from Codex files), and
`--codex-sessions-dir PATH` (an extra sessions directory; may be repeated).
Metadata and local lifecycle markers refresh at most once every 2 seconds.
An unchanged display is refreshed every 10 seconds to recover from lost content.
When the device is unavailable, retries slow down to once every 30 seconds.
The app does not automatically raise its API priority.

## Updating and uninstalling

Stop `run`, update the project files, and run `uv sync` again. Repeat
`install-hooks` for the environments you use, especially if the folder or Python
path has changed.

Before deleting the project folder, remove the integrations:

```powershell
uv run busybar-codex uninstall-hooks --client codex
uv run busybar-codex uninstall-hooks --client claude
uv run busybar-codex uninstall-hooks --client codex --wsl-distro Ubuntu
uv run busybar-codex uninstall-hooks --client claude --wsl-distro Ubuntu
```

Run only the commands for environments you connected. This app's hooks are removed;
unrelated settings remain. Its status line is removed only if it matches the
installed command. You can keep user data or remove it manually after stopping
the app; the app does not delete AI conversation history.

## Emulator and development

Without a device, you can use the [unofficial emulator](https://github.com/maxswinkels/busybar-emulator).
It also requires Git and Node.js 22+:

```powershell
.\scripts\emulator.ps1 install
.\scripts\emulator.ps1 start
```

Open <http://127.0.0.1:8080>. In a second window:

```powershell
uv run busybar-codex --address http://127.0.0.1:8080 run --no-input
```

The emulator does not replace checks of the rear display and physical controls.
You can also use [busybar-manager](https://github.com/maxswinkels/busybar-manager)
if it forwards the required HTTP requests and WebSocket; otherwise, use `--no-input`.

Required checks:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Optional checks change the real device's display or use WSL:

```powershell
$env:BUSYBAR_TEST_WSL = 'Ubuntu'
uv run pytest tests/contract/test_install.py
$env:BUSYBAR_HARDWARE_TEST = '1'
uv run --env-file .env pytest tests/integration/test_dashboard_hardware.py
```

The `render-assets` command remains available for the older static images.
For more information, see [CONTRIBUTING](CONTRIBUTING.md), [privacy](SECURITY.md),
[related-project research](docs/RESEARCH.md), and [ideas and future releases](docs/ROADMAP.md).
