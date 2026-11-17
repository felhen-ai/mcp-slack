"""Messaging tools: list channels, find users, read and post messages."""

from __future__ import annotations

from mcp.types import ToolAnnotations

from mcp_slack.client import get_client
from mcp_slack.conversations import (
    EMAIL_RE,
    list_users,
    resolve_conversation,
    resolve_user,
)
from mcp_slack.server import mcp

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
EXTERNAL_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

_MAX_USER_RESULTS = 20


@mcp.tool(annotations=READ_ONLY)
async def slack_list_channels() -> str:
    """List all Slack channels accessible by the token.

    Returns a formatted list of channel names with their IDs and topics.
    """
    client = get_client()
    channels: list[dict] = []
    cursor: str | None = None

    while True:
        kwargs: dict = {"types": "public_channel,private_channel", "limit": 200}
        if cursor:
            kwargs["cursor"] = cursor

        response = await client.conversations_list(**kwargs)
        channels.extend(response.get("channels", []))

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    if not channels:
        return "No channels found."

    lines: list[str] = []
    for ch in sorted(channels, key=lambda c: c.get("name", "")):
        name = ch.get("name", "unknown")
        cid = ch.get("id", "")
        topic = ch.get("topic", {}).get("value", "")
        member_count = ch.get("num_members", "?")
        prefix = "🔒" if ch.get("is_private") else "#"
        line = f"{prefix} {name} ({cid}) — {member_count} members"
        if topic:
            line += f" — {topic}"
        lines.append(line)

    return f"Found {len(channels)} channels:\n\n" + "\n".join(lines)


@mcp.tool(annotations=READ_ONLY)
async def slack_find_user(query: str) -> str:
    """Search workspace members to identify the exact recipient of a DM.

    Use this before slack_post_message to a person: confirm with the requester
    which listed user is the intended recipient, then post using the user ID.

    Args:
        query: An e-mail (exact lookup), or text matched case-insensitively
            against the Slack handle, display name, real name and e-mail.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("A search query is required.")

    if EMAIL_RE.match(query):
        user = await resolve_user(query)
        return f"Found 1 user:\n\n- {user.describe()}"

    needle = query.removeprefix("@").casefold()
    matches = [
        user
        for user in await list_users()
        if any(needle in field.casefold() for field in (*user.names(), user.email))
    ]

    if not matches:
        return f"No users match '{query}'."

    lines = [f"- {u.describe()}" for u in matches[:_MAX_USER_RESULTS]]
    header = f"Found {len(matches)} users"
    if len(matches) > _MAX_USER_RESULTS:
        header += f" (showing first {_MAX_USER_RESULTS}; refine the query)"
    return f"{header}:\n\n" + "\n".join(lines)


@mcp.tool(annotations=READ_ONLY)
async def slack_read_channel(channel: str, limit: int = 20) -> str:
    """Read the last N messages from a channel or direct message.

    Use it to review a conversation, including the DM with a person, before
    posting to it. Reading a DM never creates one.

    Args:
        channel: Destination: channel name (with or without #), conversation ID
            (C…, G…, D…), @user, user e-mail or user ID (U…/W…) for the
            direct message with that user.
        limit: Number of messages to retrieve (default: 20, max: 100).
    """
    client = get_client()
    limit = max(1, min(limit, 100))

    conversation = await resolve_conversation(channel, create_dm=False)

    response = await client.conversations_history(channel=conversation.id, limit=limit)
    messages = response.get("messages", [])

    if not messages:
        return f"No messages found in {conversation.label}."

    lines: list[str] = []
    for msg in reversed(messages):
        user = msg.get("user") or msg.get("bot_id") or "unknown"
        text = msg.get("text", "")
        ts = msg.get("ts", "")
        lines.append(f"[{ts}] <@{user}>: {text}")

    return f"Last {len(messages)} messages from {conversation.label}:\n\n" + "\n".join(
        lines
    )


@mcp.tool(annotations=EXTERNAL_WRITE)
async def slack_post_message(channel: str, text: str) -> str:
    """Send a message to a channel or as a direct message to a person.

    This is an external write performed immediately. Before calling it, the
    caller MUST show the requester the exact resolved destination (channel or
    person, e.g. from slack_find_user) and the exact text, and get explicit
    confirmation. For a DM, review the conversation first with
    slack_read_channel. The destination is required: there is no default
    channel, and an unknown or ambiguous destination fails without posting.
    The message is sent as the identity that owns the configured token.

    Args:
        channel: Destination: channel name (with or without #), conversation ID
            (C…, G…, D…), @user, user e-mail or user ID (U…/W…). Prefer IDs
            once the destination has been confirmed.
        text: The message text to send. Supports Slack mrkdwn.
    """
    if not (text or "").strip():
        raise ValueError("Message text is required.")

    conversation = await resolve_conversation(channel, create_dm=True)

    client = get_client()
    response = await client.chat_postMessage(channel=conversation.id, text=text)
    ts = response.get("ts", "unknown")
    posted_to = response.get("channel", conversation.id)

    return (
        f"Message sent to {conversation.label} (conversation: {posted_to}, ts: {ts})."
    )
