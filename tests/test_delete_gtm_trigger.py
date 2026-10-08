"""Tests for delete_gtm_trigger tool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_client(trigger: dict, tags: list[dict] | None = None):
    """Build a MagicMock GTM client whose triggers().get returns `trigger`,
    triggers().delete records the call, and tags().list returns `tags`.
    """
    client = MagicMock()
    triggers = client.service.accounts().containers().workspaces().triggers()
    tags_leaf = client.service.accounts().containers().workspaces().tags()

    get_req = MagicMock()
    get_req.execute = MagicMock(return_value=dict(trigger))
    triggers.get = MagicMock(return_value=get_req)

    delete_req = MagicMock()
    delete_req.execute = MagicMock(return_value=None)
    triggers.delete = MagicMock(return_value=delete_req)

    list_req = MagicMock()
    list_req.execute = MagicMock(return_value={"tag": tags or []})
    tags_leaf.list = MagicMock(return_value=list_req)

    return client, triggers, tags_leaf


class TestDeleteTriggerHappyPath:
    @pytest.mark.asyncio
    async def test_orphan_trigger_is_deleted(self):
        from fastmcp_gtm_write_tools import delete_gtm_trigger

        trigger = {"name": "Old Trigger", "triggerId": "307"}
        client, triggers, _ = _make_mock_client(trigger, tags=[])

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("62", "accounts/1/containers/2/workspaces/62"))):
            result = await delete_gtm_trigger(
                account_id="1", container_id="2", trigger_id="307", workspace_id="62"
            )

        assert result["status"] == "success"
        assert result["trigger_id"] == "307"
        assert result["trigger_name"] == "Old Trigger"
        triggers.delete.assert_called_once()
        assert triggers.delete.call_args.kwargs["path"] == \
            "accounts/1/containers/2/workspaces/62/triggers/307"


class TestDeleteTriggerReferenceGuard:
    @pytest.mark.asyncio
    async def test_refuses_when_referenced_as_firing(self):
        from fastmcp_gtm_write_tools import delete_gtm_trigger

        trigger = {"name": "Live Trigger", "triggerId": "100"}
        tags = [
            {"tagId": "10", "name": "Live Tag", "firingTriggerId": ["100"]},
            {"tagId": "11", "name": "Other Tag", "firingTriggerId": ["999"]},
        ]
        client, triggers, _ = _make_mock_client(trigger, tags=tags)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await delete_gtm_trigger(
                account_id="1", container_id="2", trigger_id="100"
            )

        assert result["status"] == "error"
        assert result["code"] == "referenced"
        assert result["trigger_id"] == "100"
        assert len(result["referencing_tags"]) == 1
        assert result["referencing_tags"][0]["tag_id"] == "10"
        assert result["referencing_tags"][0]["as"] == "firing"
        triggers.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_refuses_when_referenced_as_blocking(self):
        from fastmcp_gtm_write_tools import delete_gtm_trigger

        trigger = {"name": "Blocker Trigger", "triggerId": "462"}
        tags = [{"tagId": "97", "name": "Blocked Tag",
                 "firingTriggerId": ["96"], "blockingTriggerId": ["462"]}]
        client, triggers, _ = _make_mock_client(trigger, tags=tags)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await delete_gtm_trigger(
                account_id="1", container_id="2", trigger_id="462"
            )

        assert result["status"] == "error"
        assert result["code"] == "referenced"
        assert result["referencing_tags"][0]["as"] == "blocking"
        triggers.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_true_deletes_referenced_trigger(self):
        from fastmcp_gtm_write_tools import delete_gtm_trigger

        trigger = {"name": "Live Trigger", "triggerId": "100"}
        tags = [{"tagId": "10", "name": "Live Tag", "firingTriggerId": ["100"]}]
        client, triggers, _ = _make_mock_client(trigger, tags=tags)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await delete_gtm_trigger(
                account_id="1", container_id="2", trigger_id="100", force=True
            )

        assert result["status"] == "success"
        triggers.delete.assert_called_once()


class TestDeleteTriggerValidation:
    @pytest.mark.asyncio
    async def test_invalid_account_id_returns_error(self):
        from fastmcp_gtm_write_tools import delete_gtm_trigger

        result = await delete_gtm_trigger(
            account_id="bad", container_id="2", trigger_id="100"
        )
        assert result["status"] == "error"
        assert "account_id" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_trigger_id_returns_error(self):
        from fastmcp_gtm_write_tools import delete_gtm_trigger

        result = await delete_gtm_trigger(
            account_id="1", container_id="2", trigger_id=""
        )
        assert result["status"] == "error"
        assert "trigger_id" in result["message"]
