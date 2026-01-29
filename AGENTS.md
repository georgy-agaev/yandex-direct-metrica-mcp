# AGENTS

Working principles for the Yandex Direct + Metrica MCP server (Python stack).

## Scope
- Language: Python.
- Libraries: `tapi-yandex-direct`, `tapi-yandex-metrika`.
- MVP: Direct read/write, Metrica read-only exports.
- Runtime: Docker on macOS M1, minimal footprint.

## Objectives
- Provide reliable MCP tools for Direct and Metrica.
- Prefer raw data responses; avoid heavy normalization in MVP.
- Keep dependencies light and memory usage low.

## MCP tools policy
- Use the approved tool list in `yandex.ad/docs/tools-proposal-YYYY-MM-DD.md`.
- Add new tools only after explicit approval.
- Provide a generic `raw_call` tool only if absolutely necessary.

## Data rules
- Do not store user data unless explicitly required.
- Do not embed secrets in files; load from environment.
- For write operations, prefer Sandbox or test accounts where possible.

## Auth and secrets
- OAuth tokens must be provided via environment variables or an external secret store.
- Never log raw tokens; mask credentials in logs.

## Error handling
- Normalize API errors into clear MCP errors.
- Retry only on transient errors (timeouts, 5xx, rate limits) with backoff.
- Make errors actionable: include endpoint, request id, and hint.

## Logging
- Log requests at info level without sensitive data.
- Log errors with minimal payload and IDs for correlation.

## Testing
- Keep tests lightweight.
- Prefer mocked API responses for unit tests.
- Avoid live API calls in CI.
- Use a Python test framework (pytest recommended) once tests are added.
- Keep tests green before committing; TDD is encouraged but optional.

## Documentation
- Keep research and planning docs in `yandex.ad/docs/`.
- Update docs when the tool list or architecture changes.
- Store session notes in `yandex.ad/docs/sessions/YYYY-MM-DD_<n>_<slug>.md`.
- Each session file must include explicit sections: "Completed" and "To Do".
- Keep `yandex.ad/README.md` as the entry point for this MCP project.
- Update `yandex.ad/CHANGELOG.md` at the end of each session; latest changes go first.

## Workflow
- Changes should be incremental and reversible.
- Validate configuration and tool list before expanding scope.
- When addressing problems or decisions, propose at least three options.
- Soft guideline: split files once they exceed ~300 LOC to keep modules readable.
- Optional: add `ast-grep` rules for recurring checks if/when the tool is introduced.
- Add short, focused comments only for tricky logic or non-obvious integrations.
