"""Tests for Slack MCP tools with mocked Slack API responses.

No test reaches a live Slack workspace: the cached client is replaced by an
``AsyncMock`` before every test.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from slack_sdk.errors import SlackApiError

import mcp_slack.client as client_module
from mcp_slack.conversations import resolve_conversation, resolve_user
from mcp_slack.tools.messaging import (
    slack_find_user,
    slack_list_channels,
    slack_post_message,
    slack_read_channel,
)

ALICE = {
    "id": "U0ALICE0001",
    "name": "alice",
    "profile": {
        "display_name": "Alice",
        "real_name": "Alice Example",
        "email": "alice@example.com",
    },
}
ALICE_TWIN = {
    "id": "U0ALICE0002",
    "name": "alice.b",
    "profile": {
        "display_name": "Alice",
        "real_name": "Alice Other",
        "email": "alice.b@example.com",
    },
}
BOB = {
    "id": "U0BOB000001",
    "name": "bob",
    "profile": {"display_name": "", "real_name": "Bob Sample", "email": ""},
}
BOT = {"id": "U0BOT000001", "name": "helper", "is_bot": True, "profile": {}}
GONE = {"id": "U0GONE00001", "name": "gone", "deleted": True, "profile": {}}
SLACKBOT = {"id": "USLACKBOT", "name": "slackbot", "profile": {}}


@pytest.fixture
def slack() -> AsyncMock:
    """Install a mocked Slack client as the cached client."""
    mock = AsyncMock()
    client_module._client = mock
    client_module._config = None
    yield mock
    client_module._client = None
    client_module._config = None


def _api_error(code: str) -> SlackApiError:
    return SlackApiError(message=code, response={"ok": False, "error": code})


def _members(slack: AsyncMock, *members: dict) -> None:
    slack.users_list.return_value = {
        "members": list(members),
        "response_metadata": {"next_cursor": ""},
    }


def _channels(slack: AsyncMock, *channels: dict) -> None:
    slack.conversations_list.return_value = {
        "channels": list(channels),
        "response_metadata": {"next_cursor": ""},
    }


class TestSlackListChannels:
    async def test_returns_channels(self, slack):
        _channels(
            slack,
            {
                "id": "C123",
                "name": "general",
                "topic": {"value": "General discussion"},
                "num_members": 42,
                "is_private": False,
            },
            {
                "id": "C456",
                "name": "random",
                "topic": {"value": ""},
                "num_members": 10,
                "is_private": False,
            },
        )

        result = await slack_list_channels()

        assert "Found 2 channels" in result
        assert "general" in result
        assert "C123" in result
        assert "random" in result

    async def test_no_channels(self, slack):
        _channels(slack)

        assert "No channels found" in await slack_list_channels()

    async def test_private_channel_prefix(self, slack):
        _channels(
            slack,
            {
                "id": "C789",
                "name": "secret",
                "topic": {"value": ""},
                "num_members": 3,
                "is_private": True,
            },
        )

        assert "\U0001f512 secret" in await slack_list_channels()

    async def test_follows_pagination(self, slack):
        slack.conversations_list.side_effect = [
            {
                "channels": [{"id": "C1", "name": "a"}],
                "response_metadata": {"next_cursor": "next"},
            },
            {
                "channels": [{"id": "C2", "name": "b"}],
                "response_metadata": {"next_cursor": ""},
            },
        ]

        result = await slack_list_channels()

        assert "Found 2 channels" in result
        assert slack.conversations_list.call_args_list[1].kwargs["cursor"] == "next"


class TestResolveConversation:
    @pytest.mark.parametrize(
        "conversation_id",
        ["C0PUBLIC001", "G0PRIVATE01", "D0DIRECT001"],
        ids=["public-channel", "private-or-mpim", "direct-message"],
    )
    async def test_conversation_ids_used_as_is(self, slack, conversation_id):
        result = await resolve_conversation(conversation_id, create_dm=True)

        assert result.id == conversation_id
        slack.conversations_list.assert_not_called()
        slack.conversations_open.assert_not_called()

    @pytest.mark.parametrize("name", ["general", "#general"])
    async def test_resolves_channel_name(self, slack, name):
        _channels(
            slack,
            {"id": "CABC12300", "name": "dev"},
            {"id": "CDEF45600", "name": "general"},
        )

        result = await resolve_conversation(name, create_dm=True)

        assert result.id == "CDEF45600"
        assert "#general" in result.label

    async def test_unknown_channel_raises(self, slack):
        _channels(slack)

        with pytest.raises(ValueError, match="not found"):
            await resolve_conversation("nonexistent", create_dm=True)

    @pytest.mark.parametrize("destination", ["", "   "])
    async def test_empty_destination_raises(self, slack, destination):
        with pytest.raises(ValueError, match="destination is required"):
            await resolve_conversation(destination, create_dm=True)

        slack.conversations_list.assert_not_called()

    async def test_user_id_opens_dm(self, slack):
        slack.users_info.return_value = {"user": ALICE}
        slack.conversations_open.return_value = {"channel": {"id": "D0ALICE0001"}}

        result = await resolve_conversation("U0ALICE0001", create_dm=True)

        assert result.id == "D0ALICE0001"
        assert "@alice" in result.label
        slack.conversations_open.assert_called_once_with(users="U0ALICE0001")

    async def test_read_does_not_create_dm(self, slack):
        slack.users_info.return_value = {"user": ALICE}
        slack.conversations_open.return_value = {"channel": {"id": "D0ALICE0001"}}

        await resolve_conversation("U0ALICE0001", create_dm=False)

        slack.conversations_open.assert_called_once_with(
            users="U0ALICE0001", prevent_creation=True
        )

    async def test_read_without_existing_dm_raises(self, slack):
        slack.users_info.return_value = {"user": ALICE}
        slack.conversations_open.return_value = {"channel": {}}

        with pytest.raises(ValueError, match="no direct message"):
            await resolve_conversation("U0ALICE0001", create_dm=False)

    async def test_read_channel_not_found_maps_to_no_dm(self, slack):
        slack.users_info.return_value = {"user": ALICE}
        slack.conversations_open.side_effect = _api_error("channel_not_found")

        with pytest.raises(ValueError, match="no direct message"):
            await resolve_conversation("U0ALICE0001", create_dm=False)


class TestResolveUser:
    async def test_by_email(self, slack):
        slack.users_lookupByEmail.return_value = {"user": ALICE}

        user = await resolve_user("alice@example.com")

        assert user.id == "U0ALICE0001"
        slack.users_lookupByEmail.assert_called_once_with(email="alice@example.com")

    async def test_unknown_email_raises(self, slack):
        slack.users_lookupByEmail.side_effect = _api_error("users_not_found")

        with pytest.raises(ValueError, match="No Slack user with e-mail"):
            await resolve_user("nobody@example.com")

    async def test_unknown_user_id_raises(self, slack):
        slack.users_info.side_effect = _api_error("user_not_found")

        with pytest.raises(ValueError, match="No Slack user with ID"):
            await resolve_user("U0NOBODY001")

    async def test_other_api_errors_propagate(self, slack):
        slack.users_lookupByEmail.side_effect = _api_error("missing_scope")

        with pytest.raises(SlackApiError):
            await resolve_user("alice@example.com")

    @pytest.mark.parametrize("name", ["@alice", "@Alice Example", "@bob sample"])
    async def test_by_exact_name(self, slack, name):
        _members(slack, ALICE, BOB)

        user = await resolve_user(name)

        assert user.id in {"U0ALICE0001", "U0BOB000001"}

    async def test_partial_name_does_not_match(self, slack):
        _members(slack, ALICE)

        with pytest.raises(ValueError, match="No Slack user named"):
            await resolve_user("@ali")

    async def test_ambiguous_name_lists_candidates(self, slack):
        _members(slack, ALICE, ALICE_TWIN)

        with pytest.raises(ValueError, match="matches 2 users") as exc:
            await resolve_user("@Alice")

        assert "U0ALICE0001" in str(exc.value)
        assert "U0ALICE0002" in str(exc.value)

    async def test_ignores_bots_deleted_and_slackbot(self, slack):
        _members(slack, BOT, GONE, SLACKBOT)

        for name in ("@helper", "@gone", "@slackbot"):
            with pytest.raises(ValueError, match="No Slack user named"):
                await resolve_user(name)


class TestSlackFindUser:
    async def test_substring_search(self, slack):
        _members(slack, ALICE, ALICE_TWIN, BOB)

        result = await slack_find_user("alice")

        assert "Found 2 users" in result
        assert "U0ALICE0001" in result
        assert "U0BOB000001" not in result

    async def test_email_lookup(self, slack):
        slack.users_lookupByEmail.return_value = {"user": BOB}

        result = await slack_find_user("bob@example.com")

        assert "U0BOB000001" in result
        slack.users_list.assert_not_called()

    async def test_no_match(self, slack):
        _members(slack, ALICE)

        assert "No users match" in await slack_find_user("zzz")

    async def test_empty_query_raises(self, slack):
        with pytest.raises(ValueError, match="query is required"):
            await slack_find_user("  ")


class TestSlackReadChannel:
    async def test_reads_messages(self, slack):
        slack.conversations_history.return_value = {
            "messages": [
                {"user": "U123", "text": "Hello world", "ts": "1700000002.000"},
                {"user": "U456", "text": "Hi there", "ts": "1700000001.000"},
            ],
        }

        result = await slack_read_channel(channel="C123ABC00", limit=10)

        assert result.index("Hi there") < result.index("Hello world")
        slack.conversations_history.assert_called_once_with(
            channel="C123ABC00", limit=10
        )

    async def test_no_messages(self, slack):
        slack.conversations_history.return_value = {"messages": []}

        assert "No messages found" in await slack_read_channel(channel="C123ABC00")

    async def test_limit_clamped(self, slack):
        slack.conversations_history.return_value = {"messages": []}

        await slack_read_channel(channel="C123ABC00", limit=999)

        slack.conversations_history.assert_called_once_with(
            channel="C123ABC00", limit=100
        )

    async def test_resolves_channel_name(self, slack):
        _channels(slack, {"id": "C999ZZZ00", "name": "general"})
        slack.conversations_history.return_value = {
            "messages": [{"user": "U1", "text": "test", "ts": "1700000000.000"}],
        }

        result = await slack_read_channel(channel="general")

        slack.conversations_history.assert_called_once_with(
            channel="C999ZZZ00", limit=20
        )
        assert "test" in result

    async def test_reads_dm_by_email_without_creating_it(self, slack):
        slack.users_lookupByEmail.return_value = {"user": ALICE}
        slack.conversations_open.return_value = {"channel": {"id": "D0ALICE0001"}}
        slack.conversations_history.return_value = {
            "messages": [{"user": "U0ALICE0001", "text": "oi", "ts": "1.0"}],
        }

        result = await slack_read_channel(channel="alice@example.com")

        assert "DM with @alice" in result
        assert "oi" in result
        slack.conversations_open.assert_called_once_with(
            users="U0ALICE0001", prevent_creation=True
        )
        slack.conversations_history.assert_called_once_with(
            channel="D0ALICE0001", limit=20
        )

    async def test_bot_message_shows_bot_id(self, slack):
        slack.conversations_history.return_value = {
            "messages": [{"bot_id": "B0BOT", "text": "beep", "ts": "1.0"}],
        }

        assert "<@B0BOT>: beep" in await slack_read_channel(channel="D0DIRECT001")


class TestSlackPostMessage:
    async def test_posts_to_channel_id(self, slack):
        slack.chat_postMessage.return_value = {
            "ts": "1700000003.000",
            "channel": "C123ABC00",
        }

        result = await slack_post_message(channel="C123ABC00", text="Hello")

        assert "Message sent" in result
        assert "1700000003.000" in result
        assert "C123ABC00" in result
        slack.chat_postMessage.assert_called_once_with(
            channel="C123ABC00", text="Hello"
        )

    async def test_posts_dm_to_user_by_email(self, slack):
        slack.users_lookupByEmail.return_value = {"user": BOB}
        slack.conversations_open.return_value = {"channel": {"id": "D0BOB000001"}}
        slack.chat_postMessage.return_value = {
            "ts": "1700000005.000",
            "channel": "D0BOB000001",
        }

        result = await slack_post_message(channel="bob@example.com", text="Oi")

        slack.conversations_open.assert_called_once_with(users="U0BOB000001")
        slack.chat_postMessage.assert_called_once_with(channel="D0BOB000001", text="Oi")
        assert "DM with @bob" in result
        assert "D0BOB000001" in result

    async def test_posts_dm_to_user_by_name(self, slack):
        _members(slack, ALICE, BOB)
        slack.conversations_open.return_value = {"channel": {"id": "D0BOB000001"}}
        slack.chat_postMessage.return_value = {"ts": "1.0"}

        await slack_post_message(channel="@Bob Sample", text="Oi")

        slack.chat_postMessage.assert_called_once_with(channel="D0BOB000001", text="Oi")

    @pytest.mark.parametrize("channel", ["", "   "])
    async def test_empty_destination_never_posts(self, slack, channel):
        with pytest.raises(ValueError, match="destination is required"):
            await slack_post_message(channel=channel, text="oops")

        slack.chat_postMessage.assert_not_called()

    async def test_ambiguous_user_never_posts(self, slack):
        _members(slack, ALICE, ALICE_TWIN)

        with pytest.raises(ValueError, match="matches 2 users"):
            await slack_post_message(channel="@Alice", text="oops")

        slack.conversations_open.assert_not_called()
        slack.chat_postMessage.assert_not_called()

    async def test_unknown_channel_never_posts(self, slack):
        _channels(slack)

        with pytest.raises(ValueError, match="not found"):
            await slack_post_message(channel="nowhere", text="oops")

        slack.chat_postMessage.assert_not_called()

    async def test_empty_text_never_posts(self, slack):
        with pytest.raises(ValueError, match="text is required"):
            await slack_post_message(channel="C123ABC00", text="  ")

        slack.chat_postMessage.assert_not_called()
