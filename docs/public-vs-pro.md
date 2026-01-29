# Public vs Pro (tool access model)

Goal: publish a safe public build focused on **read-only** analytics, and keep Direct write operations in a separate **Pro** distribution.

## Public (read-only)

Recommended setting:
- `MCP_PUBLIC_READONLY=true`

Effect:
- Write tools are hidden/blocked (Direct create/update, raw calls).
- Designed for reporting, joins, and dashboard generation.

## Pro (full)

Recommended setting:
- `MCP_PUBLIC_READONLY=false`

Effect:
- Full toolset is available (still guarded by existing safety env flags like `MCP_WRITE_ENABLED`, sandbox-only policies, etc.).

## Why this split

- Reduces risk for public users (no accidental writes).
- Keeps the public surface smaller and easier to support.
- Allows a paid/pro offering without changing the core architecture.

