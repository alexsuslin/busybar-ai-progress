# Security and privacy

## Data handling

The hook boundary accepts Codex lifecycle JSON but persists only:

- session and optional turn identifiers;
- normalized state;
- timestamp;
- a fixed reason code.

The project intentionally excludes prompt text, assistant messages, tool names and arguments
except the in-memory `request_user_input` classification, approval descriptions, API tokens,
and Codex authentication data such as `auth.json`. Raw hook stdin is never logged.

Device tokens may be supplied through `BUSYBAR_CODEX_TOKEN` or a local configuration file.
Do not commit configuration, state, cache, logs, emulator checkouts, or credentials.

## Reporting a vulnerability

Please report vulnerabilities privately to the repository owner rather than opening a public
issue containing exploit details, logs, tokens, prompts, or device information. Include a
minimal reproduction with synthetic data and allow time for a fix before public disclosure.
