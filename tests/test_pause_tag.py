"""Tests for pause_tag/unpause_tag/get_gtm_variable tools."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import tool_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client(tag: dict):
    """Build a MagicMock GTM client whose tags().get() returns `tag` and
    whose tags().update() echoes back the body that was sent.

    Returns (client, tags_mock) — tags_mock is the leaf MagicMock so tests
    can inspect call_args on .get / .update.
    """
    client = MagicMock()
    tags = client.service.accounts().containers().workspaces().tags()

    get_req = MagicMock()
    get_req.execute = MagicMock(return_value=dict(tag))
    tags.get = MagicMock(return_value=get_req)

    def _update(path, body, fingerprint):
        update_req = MagicMock()
        update_req.execute = MagicMock(return_value=dict(body))
        return update_req

    tags.update = MagicMock(side_effect=_update)
    return client, tags


def _make_mock_variable_client(variable: dict):
    """Build a mock client whose variables().get() returns `variable`."""
    client = MagicMock()
    variables = client.service.accounts().containers().workspaces().variables()
    get_req = MagicMock()
    get_req.execute = MagicMock(return_value=dict(variable))
    variables.get = MagicMock(return_value=get_req)
    return client, variables


# ---------------------------------------------------------------------------
# _set_tag_paused — internal helper
# ---------------------------------------------------------------------------


class TestSetTagPaused:
    @pytest.mark.asyncio
    async def test_pause_running_tag_sets_paused_true(self):
        from gtm_mcp.write_tools import _set_tag_paused

        tag = {"name": "MT Action 1 - MPG", "tagId": "453",
               "fingerprint": "fp1", "paused": False}
        client, tags = _make_mock_client(tag)

        result = await _set_tag_paused(
            client,
            "accounts/1/containers/2/workspaces/54",
            "453",
            paused=True,
        )

        assert result["status"] == "success"
        assert result["paused"] is True
        assert result["tag_id"] == "453"
        assert result["tag_name"] == "MT Action 1 - MPG"

        update_call = tags.update.call_args
        assert update_call.kwargs["path"] == "accounts/1/containers/2/workspaces/54/tags/453"
        assert update_call.kwargs["body"]["paused"] is True
        assert update_call.kwargs["fingerprint"] == "fp1"

    @pytest.mark.asyncio
    async def test_pause_already_paused_tag_is_noop(self):
        from gtm_mcp.write_tools import _set_tag_paused

        tag = {"name": "Already Paused", "tagId": "100",
               "fingerprint": "fp1", "paused": True}
        client, tags = _make_mock_client(tag)

        result = await _set_tag_paused(
            client, "accounts/1/containers/2/workspaces/1", "100", paused=True
        )

        assert result["status"] == "noop"
        assert result["paused"] is True
        tags.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_unpause_paused_tag_sets_paused_false(self):
        from gtm_mcp.write_tools import _set_tag_paused

        tag = {"name": "Test", "tagId": "100",
               "fingerprint": "fp1", "paused": True}
        client, tags = _make_mock_client(tag)

        result = await _set_tag_paused(
            client, "accounts/1/containers/2/workspaces/1", "100", paused=False
        )

        assert result["status"] == "success"
        assert result["paused"] is False
        update_call = tags.update.call_args
        assert update_call.kwargs["body"]["paused"] is False

    @pytest.mark.asyncio
    async def test_unpause_running_tag_is_noop(self):
        from gtm_mcp.write_tools import _set_tag_paused

        # tag has no `paused` field at all (GTM API omits it when False)
        tag = {"name": "Test", "tagId": "100", "fingerprint": "fp1"}
        client, tags = _make_mock_client(tag)

        result = await _set_tag_paused(
            client, "accounts/1/containers/2/workspaces/1", "100", paused=False
        )

        assert result["status"] == "noop"
        assert result["paused"] is False
        tags.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_preserves_other_tag_fields(self):
        """Mutating only `paused` must not strip type/parameter/triggers."""
        from gtm_mcp.write_tools import _set_tag_paused

        tag = {
            "name": "MT Action 1",
            "tagId": "100",
            "type": "img",
            "fingerprint": "fp1",
            "paused": False,
            "firingTriggerId": ["99"],
            "parameter": [{"key": "url", "value": "x", "type": "template"}],
        }
        client, tags = _make_mock_client(tag)

        await _set_tag_paused(
            client, "accounts/1/containers/2/workspaces/1", "100", paused=True
        )

        body = tags.update.call_args.kwargs["body"]
        assert body["type"] == "img"
        assert body["firingTriggerId"] == ["99"]
        assert body["parameter"] == [{"key": "url", "value": "x", "type": "template"}]


# ---------------------------------------------------------------------------
# pause_tag / unpause_tag — @mcp.tool wrappers
# ---------------------------------------------------------------------------


class TestPauseTagTool:
    @pytest.mark.asyncio
    async def test_invalid_account_id_returns_error(self):
        from gtm_mcp.write_tools import pause_tag

        message = await tool_error(pause_tag(account_id="bad", container_id="2", tag_id="100"))
        assert "account_id" in message

    @pytest.mark.asyncio
    async def test_invalid_tag_id_returns_error(self):
        from gtm_mcp.write_tools import pause_tag

        message = await tool_error(pause_tag(account_id="1", container_id="2", tag_id=""))
        assert "tag_id" in message

    @pytest.mark.asyncio
    async def test_pause_tag_calls_set_paused_true(self):
        from gtm_mcp.write_tools import pause_tag

        tag = {"name": "T", "tagId": "100", "fingerprint": "fp", "paused": False}
        client, tags = _make_mock_client(tag)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await pause_tag(account_id="1", container_id="2", tag_id="100")

        assert result["status"] == "success"
        assert result["paused"] is True
        assert tags.update.call_args.kwargs["body"]["paused"] is True


class TestUnpauseTagTool:
    @pytest.mark.asyncio
    async def test_unpause_tag_calls_set_paused_false(self):
        from gtm_mcp.write_tools import unpause_tag

        tag = {"name": "T", "tagId": "100", "fingerprint": "fp", "paused": True}
        client, tags = _make_mock_client(tag)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await unpause_tag(account_id="1", container_id="2", tag_id="100")

        assert result["status"] == "success"
        assert result["paused"] is False
        assert tags.update.call_args.kwargs["body"]["paused"] is False


# ---------------------------------------------------------------------------
# get_gtm_variable
# ---------------------------------------------------------------------------


class TestGetGtmVariable:
    @pytest.mark.asyncio
    async def test_returns_full_variable_resource(self):
        from gtm_mcp.read_tools import get_gtm_variable

        variable = {
            "name": "domain",
            "variableId": "15",
            "type": "jsm",
            "parameter": [{"key": "javascript", "value": "function() { return 'x'; }",
                           "type": "template"}],
            "fingerprint": "fp",
        }
        client, variables = _make_mock_variable_client(variable)

        with patch("gtm_mcp.read_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.read_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", "accounts/1/containers/2/workspaces/54"))):
            result = await get_gtm_variable(
                account_id="1", container_id="2", variable_id="15", workspace_id="54"
            )

        assert result["status"] == "success"
        assert result["variable"]["name"] == "domain"
        assert result["variable"]["variableId"] == "15"
        assert result["variable"]["parameter"][0]["key"] == "javascript"

        get_call = variables.get.call_args
        assert get_call.kwargs["path"] == "accounts/1/containers/2/workspaces/54/variables/15"

    @pytest.mark.asyncio
    async def test_invalid_variable_id_returns_error(self):
        from gtm_mcp.read_tools import get_gtm_variable

        message = await tool_error(get_gtm_variable(
            account_id="1", container_id="2", variable_id="bad"
        ))
        assert "variable_id" in message
