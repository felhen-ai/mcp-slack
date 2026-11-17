"""Destination and user resolution for Slack conversations.

Destination grammar accepted by the tools:

- ``#name`` or ``name``: a public or private channel name visible to the token.
- ``C…``, ``G…`` or ``D…``: a conversation ID (public channel, private channel or
  multi-party DM, direct message). Used as-is, never resolved as a name.
- ``@name``: a workspace member, matched exactly against the Slack handle,
  display name or real name. Opens or reuses the direct message with that user.
- ``person@example.com``: a workspace member looked up by e-mail.
- ``U…`` or ``W…``: a user ID. Opens or reuses the direct message with that user.

Resolution never falls back to another destination: an empty, unknown or
ambiguous destination raises ``ValueError`` with an actionable message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from slack_sdk.errors import SlackApiError

from mcp_slack.client import get_client

CONVERSATION_ID_RE = re.compile(r"^[CGD][A-Z0-9]{8,}$")
USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{8,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class Conversation:
    """A resolved Slack conversation and a human-readable description of it."""

    id: str
    label: str


@dataclass(frozen=True, slots=True)
class User:
    """The subset of a Slack user record that the tools expose."""

    id: str
    handle: str
    display_name: str
    real_name: str
    email: str

    @classmethod
    def from_api(cls, member: dict[str, Any]) -> User:
        profile = member.get("profile", {}) or {}
        return cls(
            id=member.get("id", ""),
            handle=member.get("name", ""),
            display_name=profile.get("display_name", "") or "",
            real_name=profile.get("real_name", "") or member.get("real_name", "") or "",
            email=profile.get("email", "") or "",
        )

    def names(self) -> list[str]:
        return [n for n in (self.handle, self.display_name, self.real_name) if n]

    def describe(self) -> str:
        parts = [f"@{self.handle}" if self.handle else self.id]
        if self.real_name:
            parts.append(self.real_name)
        if self.display_name and self.display_name != self.real_name:
            parts.append(f"display: {self.display_name}")
        if self.email:
            parts.append(self.email)
        return f"{' — '.join(parts)} ({self.id})"


async def resolve_conversation(destination: str, *, create_dm: bool) -> Conversation:
    """Resolve a destination string into a conversation.

    Args:
        destination: Destination in the grammar described in the module docstring.
        create_dm: When the destination is a user, open the DM if it does not exist
            yet (writes). When False, only an existing DM is returned (reads).

    Raises:
        ValueError: The destination is empty, unknown, ambiguous or has no DM.
    """
    dest = (destination or "").strip()
    if not dest:
        raise ValueError(
            "A destination is required: a channel name or ID, @user, e-mail or "
            "user ID. No default destination is used."
        )

    if CONVERSATION_ID_RE.match(dest):
        return Conversation(id=dest, label=dest)

    if dest.startswith("@") or EMAIL_RE.match(dest) or USER_ID_RE.match(dest):
        user = await resolve_user(dest)
        return await _open_dm(user, create=create_dm)

    name = dest.removeprefix("#")
    channel_id = await _find_channel_id(name)
    return Conversation(id=channel_id, label=f"#{name} ({channel_id})")


async def resolve_user(identifier: str) -> User:
    """Resolve exactly one workspace member from @name, e-mail or user ID.

    Raises:
        ValueError: No member or more than one member matches.
    """
    ident = identifier.strip()
    client = get_client()

    if USER_ID_RE.match(ident):
        try:
            response = await client.users_info(user=ident)
        except SlackApiError as exc:
            if _error_code(exc) == "user_not_found":
                raise ValueError(f"No Slack user with ID {ident}.") from exc
            raise
        return User.from_api(response.get("user", {}))

    if EMAIL_RE.match(ident):
        try:
            response = await client.users_lookupByEmail(email=ident)
        except SlackApiError as exc:
            if _error_code(exc) == "users_not_found":
                raise ValueError(f"No Slack user with e-mail {ident}.") from exc
            raise
        return User.from_api(response.get("user", {}))

    wanted = ident.removeprefix("@").strip().casefold()
    if not wanted:
        raise ValueError("Empty user name after '@'.")

    matches = [
        user
        for user in await list_users()
        if any(n.casefold() == wanted for n in user.names())
    ]
    if not matches:
        raise ValueError(
            f"No Slack user named '{ident}'. Use slack_find_user to search, then "
            "pass the user ID or e-mail."
        )
    if len(matches) > 1:
        candidates = "\n".join(f"- {u.describe()}" for u in matches)
        raise ValueError(
            f"'{ident}' matches {len(matches)} users; pass the user ID or e-mail "
            f"of the intended person:\n{candidates}"
        )
    return matches[0]


async def list_users() -> list[User]:
    """Return active human members of the workspace (no bots, no deactivated)."""
    client = get_client()
    users: list[User] = []
    cursor: str | None = None

    while True:
        kwargs: dict[str, Any] = {"limit": _PAGE_SIZE}
        if cursor:
            kwargs["cursor"] = cursor
        response = await client.users_list(**kwargs)
        for member in response.get("members", []):
            if (
                member.get("deleted")
                or member.get("is_bot")
                or member.get("id") == "USLACKBOT"
            ):
                continue
            users.append(User.from_api(member))

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return users


async def _open_dm(user: User, *, create: bool) -> Conversation:
    client = get_client()
    kwargs: dict[str, Any] = {"users": user.id}
    if not create:
        kwargs["prevent_creation"] = True

    try:
        response = await client.conversations_open(**kwargs)
    except SlackApiError as exc:
        if not create and _error_code(exc) == "channel_not_found":
            raise ValueError(
                f"There is no direct message with {user.describe()} yet."
            ) from exc
        raise

    channel_id = (response.get("channel") or {}).get("id", "")
    if not channel_id:
        raise ValueError(f"There is no direct message with {user.describe()} yet.")
    return Conversation(id=channel_id, label=f"DM with {user.describe()}")


async def _find_channel_id(name: str) -> str:
    client = get_client()
    cursor: str | None = None

    while True:
        kwargs: dict[str, Any] = {
            "types": "public_channel,private_channel",
            "limit": _PAGE_SIZE,
        }
        if cursor:
            kwargs["cursor"] = cursor

        response = await client.conversations_list(**kwargs)
        for ch in response.get("channels", []):
            if ch.get("name") == name:
                return ch["id"]

        cursor = response.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    raise ValueError(
        f"Channel '{name}' not found. Use the exact channel name or ID; for a "
        "direct message use @user, an e-mail or a user ID."
    )


def _error_code(exc: SlackApiError) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return ""
    try:
        return response.get("error", "") or ""
    except AttributeError:
        return ""
