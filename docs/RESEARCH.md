# Related projects and design choices

Reviewed on September 11, 2026. The review covered READMEs, licenses and relevant
source files, beyond star counts. No code was copied from these projects;
the ideas were implemented independently. The exception for graphics is the licensed
Simple Icons listed in [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md).

| Project | Useful ideas | What was adopted here / limitations |
| --- | --- | --- |
| [futurepaul/busybar-codex](https://github.com/futurepaul/busybar-codex) — MIT | Local rollout files, two displays, approval with the large button through busylib | Separate display roles and the standard WebSocket interface. This project shows only safe metadata, without activity text. That project's automatic startup targets macOS |
| [kylewhirl/busybar-codex](https://github.com/kylewhirl/busybar-codex) — MIT | Encoder, task selection, separate control screens | Adopted the idea of an explicitly selected session and control hints. Its deep integration with Codex Micro/macOS uses an internal interface and CDP; this is not a portable Windows API |
| [m1ckc3s/claude-status-bar](https://github.com/m1ckc3s/claude-status-bar) — MIT | Short lifecycle hooks, merging configuration entries during installation | Added an installer that can run repeatedly and removes only its own hooks. Existing status lines are preserved. Complete copies of user settings are not created because they may contain credentials |
| [rullerzhou-afk/clawd-on-desk](https://github.com/rullerzhou-afk/clawd-on-desk) | Separate Codex/Claude adapters, statusLine, WSL and Windows differences | Added an explicit WSL bridge and separate metadata directories. The assumption that localhost behaves identically in every WSL networking mode cannot be carried over. Hooks in this project do not use the network |
| [eunai/busybar-relay](https://github.com/eunai/busybar-relay) — MIT | Focus on the moment when a person needs to respond | Preserved the distinction between QUESTION and DONE. At the time of review, the repository mainly contained documentation, rather than a ready-to-use portable implementation |
| [maxswinkels/busybar-apps](https://github.com/maxswinkels/busybar-apps) | App gallery and a shared way to launch apps through the manager | Used as a source of compatibility information and ideas for future packaging. The manager and emulator remain optional |

## Why one solution does not cover every window

Events come from the assistant process, rather than the window title. For example,
VS Code can run a Windows CLI, an integrated extension or an extension inside WSL.
These options have different home directories and available data sources.

Claude [VS Code](https://code.claude.com/docs/en/vs-code#configure-claude-code)
and local [Desktop Code](https://code.claude.com/docs/en/desktop#shared-configuration)
share hooks. The terminal
[statusLine](https://code.claude.com/docs/en/statusline#available-data) provides richer
telemetry, but the presence of hook settings does not prove that the GUI invokes statusLine.
Status support and percentage support are therefore documented separately.

Codex hooks provide lifecycle events, while local rollout metadata provides the model,
effort, latest context window occupancy and rate limits. The rollout format is an
implementation detail, so the adapter limits its reads and returns N/A when recognized
fields are unavailable. It does not open authentication files or replay private account requests.

For WSL, the chosen approach runs a Windows `.exe` through standard interop: the same
normalization code writes to the same Windows directory. There is no HTTP listener,
open port, API token or raw POST containing hook data. This differs from network relay
solutions and follows the project's rule that hooks perform local writes only.

## Device capabilities

The official [busylib](https://github.com/busy-app/busylib-py) provides HTTP
for the display and a [state WebSocket](https://busy-app.github.io/busylib-py/guides/device-state/)
for controls. Elements are updated by ID; omitting an element does not delete it.
The app therefore sends a stable set of elements and explicitly hides stale ones.
This was also verified on physical hardware running API 27.5.0.

Physical buttons retain their built-in behavior. Exclusive control capture, control of
ordinary Chat/Cowork sessions and a reliable universal bridge to private UI interfaces
are not claimed as completed features. Next steps are listed in [ROADMAP](ROADMAP.md).

## Activity and effort sources

Codex [PermissionRequest](https://learn.chatgpt.com/docs/hooks#permissionrequest) runs
before the approval decision. An automatic reviewer or hook can resolve it, so this app
shows CHECK. Tool hooks supply TOOL and the subsequent THINK phase; compact hooks
supply COMPACT. These labels describe lifecycle events and contain no task text. Claude
[idle notifications](https://code.claude.com/docs/en/hooks#notification) can fire after
a completed response; they do not mean a blocking question and are ignored.

Codex [model metadata](https://learn.chatgpt.com/docs/app-server#list-models-modellist)
defines supported effort levels per model. The display uses an exact-model lookup in the
bounded local model cache, without starting an app-server or calling an account service.
A model with five levels has five pixels; a model with six has six. Missing capabilities
hide the scale. Claude [statusLine](https://code.claude.com/docs/en/statusline) supplies
a selected effort level without a supported-level list, so no Claude scale is inferred.
