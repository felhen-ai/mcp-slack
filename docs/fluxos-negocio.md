---
title: Product flows — MCP Slack
kind: guide
area: product
project: mcp-slack
collection: mcp-slack
owner: maintainers
status: current
canonical: docs/fluxos-negocio.md
globalRef: qmd://mcp-slack/docs/fluxos-negocio.md
reviewCadenceDays: 90
lastReviewedAt: 2026-11-17
sourceRefs:
  - README.md
  - src/mcp_slack/tools/messaging.py
  - src/mcp_slack/conversations.py
related:
  - docs/arquitetura.md
  - docs/operacao.md
  - docs/index.md
supersedes: []
supersededBy: []
sensitivity: public
---

# Product flows

MCP Slack exposes four tools to an MCP client. The operator supplies one Slack
OAuth token and the client invokes tools through the stdio server. Every action
runs as the identity that owns the token: the app's bot user for a bot token,
or the authorizing person for a user token.

## Destinations

`slack_read_channel` and `slack_post_message` take a destination that is
resolved before any Slack call that reads or writes messages:

- `#name` or `name` resolves a public or private channel by exact name through
  `conversations.list`.
- `C…`, `G…` and `D…` conversation IDs are used as-is and never looked up as
  names.
- `@name`, an e-mail or a `U…`/`W…` user ID resolves exactly one workspace
  member (`users.list`, `users.lookupByEmail` or `users.info`) and then the
  direct message with that member through `conversations.open`.

Name matching for `@name` is exact and case-insensitive against the Slack
handle, display name and real name, and skips bots, deactivated members and
Slackbot. Zero matches, several matches, an unknown e-mail or user ID, or an
empty destination raise an explicit error; there is no default destination and
no fallback to another conversation.

## List channels

`slack_list_channels` calls `conversations.list` for public and private channels
visible to the token. It follows Slack cursors, sorts the combined result by
name and returns formatted names, IDs, topics, member counts and privacy
markers.

The current implementation accumulates the complete visible inventory before
responding. Bounded pagination and reuse of channel discovery are tracked in
[Issue #11](https://github.com/felhen-ai/mcp-slack/issues/11).

## Find a user

`slack_find_user` looks a member up by exact e-mail, or searches active human
members by case-insensitive substring of handle, display name, real name and
e-mail. It returns at most 20 members with ID, handle, names and e-mail, so the
caller can confirm the intended recipient before posting.

## Read messages

`slack_read_channel` resolves the destination, clamps the requested limit to
1–100 and loads one `conversations.history` page. For a person, it opens the
DM with `prevent_creation`, so reading never creates a conversation; when no DM
exists it returns an explicit error. Messages are formatted from oldest to
newest with Slack timestamps and raw user or bot IDs.

- User display-name resolution is tracked in
  [Issue #4](https://github.com/felhen-ai/mcp-slack/issues/4).
- Reading thread replies is tracked in
  [Issue #1](https://github.com/felhen-ai/mcp-slack/issues/1).

## Post a message

`slack_post_message` requires a non-empty destination and text, resolves the
destination (opening or reusing the DM for a person) and then calls
`chat.postMessage`. The receipt names the resolved destination, the conversation
ID and the Slack timestamp.

Posting is an external side effect. The tool contract tells callers to confirm
the resolved destination and exact text with the requester before calling it,
and, for a DM, to review the conversation first. Thread replies and Block Kit
are tracked in Issues
[#1](https://github.com/felhen-ai/mcp-slack/issues/1) and
[#3](https://github.com/felhen-ai/mcp-slack/issues/3).

## Current boundaries

- The server uses stdio transport.
- One token is configured per process; it fixes the acting identity.
- A bot token reads only channels the bot belongs to and its own DMs.
- The Slack client and configuration are initialized lazily and cached in
  process memory.
- Tools return formatted text; structured MCP responses are tracked in
  [Issue #14](https://github.com/felhen-ai/mcp-slack/issues/14).
- The repository does not proxy or persist Slack workspace content.
