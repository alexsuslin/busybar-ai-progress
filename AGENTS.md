# Project guidance

- Use `request_user_input` for blocking questions whenever that tool is available. The BUSY Bar
  integration uses this lifecycle signal to show `QUESTION?` reliably.
- Never log or persist raw Codex hook stdin, prompt text, tool arguments, assistant messages,
  approval descriptions, access tokens, or Codex authentication files.
- Hook handlers must only perform bounded local file writes. They must not contact BUSY Bar,
  OpenAI, or any other external service.
- Implement behavior with test-driven development and run `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv run pyright` before declaring a change complete.
