---
title: Architecture — MCP Slack
kind: architecture
area: engineering
project: mcp-slack
collection: mcp-slack
owner: maintainers
status: current
canonical: docs/arquitetura.md
globalRef: qmd://mcp-slack/docs/arquitetura.md
reviewCadenceDays: 90
lastReviewedAt: 2026-11-17
sourceRefs:
  - pyproject.toml
  - src/mcp_slack
related:
  - docs/fluxos-negocio.md
  - docs/operacao.md
  - docs/index.md
supersedes: []
supersededBy: []
sensitivity: public
---
# Architecture

## Components

| Component | Responsibility |
| --- | --- |
| `server.py` | Creates the FastMCP server, imports the messaging module and starts stdio transport. |
| `config.py` | Reads the required Slack token from environment variables. |
| `client.py` | Lazily creates and caches the Slack configuration and asynchronous Web API client. |
| `conversations.py` | Resolves destinations (channel names, conversation IDs, users by name, e-mail or ID) into conversations, opening DMs when posting. |
| `tools/messaging.py` | Implements channel listing, user lookup, conversation history and message posting, with MCP safety annotations. |

## Request path

```text
MCP client
  -> FastMCP tool registration
  -> environment-backed SlackConfig
  -> cached AsyncWebClient
  -> Slack Web API
  -> formatted text response
```

The server has no application database. Slack remains the system of record;
only configuration and the SDK client are retained in process memory.

## Authentication and scope boundary

`SLACK_BOT_TOKEN` enters through the environment and is passed to the Slack SDK.
The token fixes the acting identity: a bot token acts as the app's bot user, a
user token as the authorizing person. The identity sees only conversations and
operations allowed by its OAuth scopes and membership. The tool-to-scope matrix
is maintained in `README.md`.

## Read and write boundary

Channel listing, user lookup and history calls are observational and carry
read-only MCP annotations. Reading a person's DM uses `conversations.open` with
`prevent_creation`, so it never creates a conversation. `slack_post_message` is
annotated as a non-idempotent external write: it requires an explicit
destination, resolves it completely before calling `chat.postMessage`, and
fails without posting when the destination is empty, unknown or ambiguous.
`tests/test_server.py` fails when a tool omits its safety annotations.

## Resilience boundary

The current client is created without custom retry handlers. Rate-limit and
method-aware retry behavior are tracked in
[Issue #2](https://github.com/felhen-ai/mcp-slack/issues/2). Stable,
redacted error mapping is tracked in
[Issue #10](https://github.com/felhen-ai/mcp-slack/issues/10).

## Known structural gaps

- Channel discovery and name resolution are unbounded; see Issue #11.
- Member lookup by name scans `users.list` on every call.
- Responses are formatted strings rather than typed MCP content; see Issue #14.
- The version hook references a removed file; see Issue #12.
