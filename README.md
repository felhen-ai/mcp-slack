# mcp-slack

MCP server for Slack integration, built with FastMCP. Provides tools for
listing channels, finding workspace members, reading channel and direct-message
history, and posting to a channel or as a direct message (DM) to a person.

Listing, user lookup and reading are observational. `slack_post_message`
performs an external write immediately when invoked, so callers must confirm
the resolved destination and the exact message text with the requester before
calling it. There is no default destination: an empty, unknown or ambiguous
destination fails without posting.

## Install

```bash
pip install -e ".[dev]"
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | Yes | Slack OAuth token. A Bot User OAuth Token (`xoxb-...`) reads and posts as the app's bot user; a User OAuth Token (`xoxp-...`) acts as the person who authorized it. |

Copy `.env.example` to `.env` and fill in your values.

`SLACK_DEFAULT_CHANNEL` is no longer read. Earlier versions posted to it when
`slack_post_message` received an empty channel; pass the destination explicitly
in every call instead.

## Tools

| Tool | Description |
|------|-------------|
| `slack_list_channels` | List all channels accessible by the token |
| `slack_find_user(query)` | Find workspace members by e-mail (exact) or by handle, display name, real name or e-mail substring |
| `slack_read_channel(channel, limit?)` | Read the last N messages (default: 20, max: 100) of a channel or of the DM with a person; never creates a DM |
| `slack_post_message(channel, text)` | Post to a channel, or open (or reuse) the DM with a person and post there |

Every tool declares MCP safety annotations: the three read tools are marked
read-only; `slack_post_message` is marked as a non-idempotent external write.

### Destinations

The `channel` parameter of `slack_read_channel` and `slack_post_message`
accepts:

| Form | Example | Resolves to |
|------|---------|-------------|
| Channel name, with or without `#` | `general`, `#general` | Public or private channel visible to the token |
| Conversation ID | `C0123456789`, `G0123456789`, `D0123456789` | Used as-is (channel, private channel or multi-party DM, direct message) |
| `@` + exact handle, display name or real name | `@jane.doe`, `@Jane Doe` | DM with that member; fails when zero or several members match |
| E-mail | `jane@example.com` | DM with the member that owns the e-mail |
| User ID | `U0123456789`, `W0123456789` | DM with that member |

Bots, deactivated members and Slackbot are never matched by name. When a name
matches several members, the error lists the candidates so the caller can pass
the intended user ID or e-mail.

### Sending a DM safely

1. `slack_find_user` to identify the recipient; confirm the listed person with
   the requester.
2. `slack_read_channel` with the user ID to review the existing conversation.
3. Show the requester the destination and the exact text; post only after
   explicit confirmation, using the user ID.

The message is sent as the identity that owns the token. With a bot token, the
recipient sees a DM from the app's bot user, and only the bot's own DMs can be
read; reading or writing a person's DMs requires that person's user token.

## Slack App Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **OAuth & Permissions**, add the required scopes for the tools you want
   to use (Bot Token Scopes for a bot token, User Token Scopes for a user token):

   | Tool | Required scopes |
   |------|-----------------|
   | `slack_list_channels` | `channels:read`, `groups:read` |
   | `slack_find_user` | `users:read`, `users:read.email` |
   | `slack_read_channel` (channels) | `channels:history`, `groups:history`, plus `channels:read`, `groups:read` to resolve names |
   | `slack_read_channel` (DMs) | `im:history`, `im:write`, `users:read`, `users:read.email` |
   | `slack_post_message` (channels) | `chat:write`, plus `channels:read`, `groups:read` to resolve names |
   | `slack_post_message` (DMs) | `chat:write`, `im:write`, `users:read`, `users:read.email` |

   *`conversations.open` (scope `im:write`) locates the DM with a person; reads
   pass `prevent_creation` so they never create one. Multi-party DMs are
   supported by conversation ID (`G...`) and need `mpim:history` to read. A bot
   token only sees channels it is a member of.*

3. Install the app to your workspace (reinstall after adding scopes)
4. Copy the OAuth token to `SLACK_BOT_TOKEN`
5. Invite the bot to channels it should access: `/invite @your-bot-name`

### Troubleshooting: `missing_scope` Error
If a tool fails with a `missing_scope` error, the token lacks a permission the
tool needs. Check the error message to see which scope is missing,
cross-reference it with the table above, add the scope in your Slack App's
**OAuth & Permissions** page and reinstall the app to your workspace.

## Usage

### Standalone

```bash
mcp-slack
```

### Claude Code

Keep the token out of command-line arguments. One option is a local `.env`
file (mode `600`, never committed) loaded by `uv`:

```bash
claude mcp add --scope user slack -- \
  uv run --directory /path/to/mcp-slack --env-file /path/to/mcp-slack/.env mcp-slack
```

### Claude Desktop config

```json
{
  "mcpServers": {
    "slack": {
      "command": "mcp-slack",
      "env": {
        "SLACK_BOT_TOKEN": "xoxb-your-token"
      }
    }
  }
}
```

## Development

```bash
pip install -e ".[dev]"
ruff check src/ tests/
ruff format src/ tests/
pytest
```

## License

MIT

## Documentation and roadmap

- [Current product flows](docs/fluxos-negocio.md)
- [Architecture](docs/arquitetura.md)
- [Operations](docs/operacao.md)
- [Documentation index](docs/index.md)
- [Open roadmap items](https://github.com/felhen-ai/mcp-slack/issues)

Priorities live in GitHub Issues and Projects. Delivery history lives in closed
Issues, pull requests and GitHub Releases.
