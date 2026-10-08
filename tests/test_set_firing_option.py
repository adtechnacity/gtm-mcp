"""Tests for set_tags_firing_option_batch tool and its validation."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import tool_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_multi_tag_client(tags_by_id: dict):
    """Mock GTM client whose tags().get(path=...) returns the tag matching the
    trailing id in `path`, and whose tags().update() echoes the sent body.

    Returns (client, tags_mock).
    """
    client = MagicMock()
    tags = client.service.accounts().containers().workspaces().tags()

    def _get(path):
        tag_id = path.rsplit("/", 1)[-1]
        req = MagicMock()
        req.execute = MagicMock(return_value=dict(tags_by_id[tag_id]))
        return req

    def _update(path, body, fingerprint):
        req = MagicMock()
        req.execute = MagicMock(return_value=dict(body))
        return req

    tags.get = MagicMock(side_effect=_get)
    tags.update = MagicMock(side_effect=_update)
    return client, tags


_WS_PARENT = ("101", "accounts/1/containers/2/workspaces/101")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    async def test_invalid_firing_option_returns_error(self):
        from gtm_mcp.write_tools import set_tags_firing_option_batch

        message = await tool_error(set_tags_firing_option_batch(
            account_id="1", container_id="2", tag_ids=["100"],
            firing_option="oncePerWeek",
        ))
        assert "firing_option" in message

    @pytest.mark.asyncio
    async def test_invalid_account_id_returns_error(self):
        from gtm_mcp.write_tools import set_tags_firing_option_batch

        message = await tool_error(set_tags_firing_option_batch(
            account_id="bad", container_id="2", tag_ids=["100"],
            firing_option="oncePerLoad",
        ))
        assert "account_id" in message


# ---------------------------------------------------------------------------
# Batch behavior
# ---------------------------------------------------------------------------


class TestBatch:
    @pytest.mark.asyncio
    async def test_sets_firing_option_on_mismatched_tags(self):
        from gtm_mcp.write_tools import set_tags_firing_option_batch

        tags = {
            "298": {"name": "MT Action 1 CTA Click", "tagId": "298", "type": "img",
                    "fingerprint": "fp298", "tagFiringOption": "oncePerEvent",
                    "firingTriggerId": ["296", "297"]},
            "300": {"name": "MT Action 2 CTA Visible", "tagId": "300", "type": "img",
                    "fingerprint": "fp300", "tagFiringOption": "oncePerEvent",
                    "firingTriggerId": ["299"]},
        }
        client, tags_mock = _make_multi_tag_client(tags)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=_WS_PARENT)):
            result = await set_tags_firing_option_batch(
                account_id="1", container_id="2", tag_ids=["298", "300"],
                firing_option="oncePerLoad", workspace_id="101",
            )

        assert result["status"] == "success"
        assert len(result["updated"]) == 2
        # every update body carries the new firing option
        for call in tags_mock.update.call_args_list:
            assert call.kwargs["body"]["tagFiringOption"] == "oncePerLoad"
        # surfaced per-tag for the caller to confirm
        assert all(e.get("firing_option") == "oncePerLoad" for e in result["updated"])

    @pytest.mark.asyncio
    async def test_skips_tag_already_at_target(self):
        from gtm_mcp.write_tools import set_tags_firing_option_batch

        tags = {
            "100": {"name": "MT Action 1", "tagId": "100", "type": "img",
                    "fingerprint": "fp100", "tagFiringOption": "oncePerLoad"},
        }
        client, tags_mock = _make_multi_tag_client(tags)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=_WS_PARENT)):
            result = await set_tags_firing_option_batch(
                account_id="1", container_id="2", tag_ids=["100"],
                firing_option="oncePerLoad", workspace_id="101",
            )

        assert result["status"] == "success"
        assert len(result["skipped"]) == 1
        tags_mock.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_preserves_other_tag_fields(self):
        from gtm_mcp.write_tools import set_tags_firing_option_batch

        tags = {
            "239": {"name": "Exit Capture CTA Click", "tagId": "239", "type": "img",
                    "fingerprint": "fp239", "tagFiringOption": "oncePerEvent",
                    "firingTriggerId": ["238"],
                    "parameter": [{"key": "url", "value": "x", "type": "template"}]},
        }
        client, tags_mock = _make_multi_tag_client(tags)

        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=_WS_PARENT)):
            await set_tags_firing_option_batch(
                account_id="1", container_id="2", tag_ids=["239"],
                firing_option="oncePerLoad", workspace_id="101",
            )

        body = tags_mock.update.call_args.kwargs["body"]
        assert body["type"] == "img"
        assert body["firingTriggerId"] == ["238"]
        assert body["parameter"] == [{"key": "url", "value": "x", "type": "template"}]
        assert body["tagFiringOption"] == "oncePerLoad"
