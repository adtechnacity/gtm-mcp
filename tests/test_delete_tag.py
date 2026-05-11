"""Tests for delete_tag tool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_client(tag: dict):
    """Build a MagicMock GTM client whose tags().get() returns `tag` and
    whose tags().delete() records the call.

    Returns (client, tags_mock) — tags_mock is the leaf MagicMock so tests
    can inspect call_args on .get / .delete.
    """
    client = MagicMock()
    tags = client.service.accounts().containers().workspaces().tags()

    get_req = MagicMock()
    get_req.execute = MagicMock(return_value=dict(tag))
    tags.get = MagicMock(return_value=get_req)

    delete_req = MagicMock()
    delete_req.execute = MagicMock(return_value=None)
    tags.delete = MagicMock(return_value=delete_req)

    return client, tags


class TestDeleteTagHappyPath:
    @pytest.mark.asyncio
    async def test_paused_tag_is_deleted(self):
        from fastmcp_gtm_write_tools import delete_tag

        tag = {"name": "Old MPG Tag", "tagId": "453",
               "fingerprint": "fp1", "paused": True}
        client, tags = _make_mock_client(tag)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", "accounts/1/containers/2/workspaces/54"))):
            result = await delete_tag(
                account_id="1", container_id="2", tag_id="453", workspace_id="54"
            )

        assert result["status"] == "success"
        assert result["tag_id"] == "453"
        assert result["tag_name"] == "Old MPG Tag"
        tags.delete.assert_called_once()
        delete_call = tags.delete.call_args
        assert delete_call.kwargs["path"] == "accounts/1/containers/2/workspaces/54/tags/453"
