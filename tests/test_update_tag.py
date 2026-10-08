"""Tests for the update_tag tool (partial in-place tag update + tag sequencing)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_single_tag_client(tag: dict):
    """Mock GTM client whose tags().get(path=...) returns a copy of `tag` and
    whose tags().update() echoes the sent body.

    Returns (client, tags_mock).
    """
    client = MagicMock()
    tags = client.service.accounts().containers().workspaces().tags()

    def _get(path):
        req = MagicMock()
        req.execute = MagicMock(return_value=dict(tag))
        return req

    def _update(path, body, fingerprint):
        req = MagicMock()
        req.execute = MagicMock(return_value=dict(body))
        return req

    tags.get = MagicMock(side_effect=_get)
    tags.update = MagicMock(side_effect=_update)
    return client, tags


_WS_PARENT = ("113", "accounts/1/containers/2/workspaces/113")


def _yahoo_tag():
    return {
        "name": "Yahoo DSP A1 Conversion", "tagId": "504", "type": "html",
        "fingerprint": "fp504", "tagFiringOption": "oncePerEvent",
        "firingTriggerId": ["502"],
        "parameter": [{"type": "template", "key": "html", "value": "<script>x</script>"}],
    }


def _maven_tag():
    return {
        "name": "MT Action 1", "tagId": "100", "type": "img",
        "fingerprint": "fp100", "tagFiringOption": "oncePerLoad",
        "firingTriggerId": ["99", "452", "491"], "parentFolderId": "426",
        "parameter": [{"type": "template", "key": "url", "value": "u"}],
    }


def _patched(client):
    return (
        patch("gtm_mcp.write_tools.get_gtm_client", return_value=client),
        patch("gtm_mcp.write_tools._resolve_workspace_parent",
              new=AsyncMock(return_value=_WS_PARENT)),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    async def test_invalid_tag_id_returns_error(self):
        from gtm_mcp.write_tools import update_tag

        result = await update_tag(account_id="1", container_id="2", tag_id="bad",
                                  name="x")
        assert result["status"] == "error"
        assert "tag_id" in result["message"]

    @pytest.mark.asyncio
    async def test_nothing_to_update_returns_error(self):
        from gtm_mcp.write_tools import update_tag

        result = await update_tag(account_id="1", container_id="2", tag_id="504")
        assert result["status"] == "error"
        assert "nothing to update" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_firing_option_returns_error(self):
        from gtm_mcp.write_tools import update_tag

        result = await update_tag(account_id="1", container_id="2", tag_id="504",
                                  tag_firing_option="oncePerWeek")
        assert result["status"] == "error"
        assert "firing_option" in result["message"] or "firing option" in result["message"].lower()


# ---------------------------------------------------------------------------
# Tag sequencing (teardownTag)
# ---------------------------------------------------------------------------


class TestSequencing:
    @pytest.mark.asyncio
    async def test_teardown_tag_name_writes_correct_shape(self):
        from gtm_mcp.write_tools import update_tag

        client, tags = _make_single_tag_client(_maven_tag())
        p1, p2 = _patched(client)
        with p1, p2:
            result = await update_tag(
                account_id="1", container_id="2", tag_id="100",
                teardown_tag_name="Yahoo DSP A1 Conversion", workspace_id="113",
            )

        assert result["status"] == "success"
        body = tags.update.call_args.kwargs["body"]
        assert body["teardownTag"] == [
            {"tagName": "Yahoo DSP A1 Conversion", "stopTeardownOnFailure": False}
        ]
        # preserves identity + everything else
        assert body["tagId"] == "100"
        assert body["firingTriggerId"] == ["99", "452", "491"]
        assert body["parameter"] == [{"type": "template", "key": "url", "value": "u"}]

    @pytest.mark.asyncio
    async def test_setup_tag_name_and_stop_on_failure(self):
        from gtm_mcp.write_tools import update_tag

        client, tags = _make_single_tag_client(_maven_tag())
        p1, p2 = _patched(client)
        with p1, p2:
            await update_tag(
                account_id="1", container_id="2", tag_id="100",
                setup_tag_name="Some Setup Tag", stop_on_failure=True,
                workspace_id="113",
            )

        body = tags.update.call_args.kwargs["body"]
        assert body["setupTag"] == [
            {"tagName": "Some Setup Tag", "stopOnSetupFailure": True}
        ]


# ---------------------------------------------------------------------------
# Partial update behavior
# ---------------------------------------------------------------------------


class TestPartialUpdate:
    @pytest.mark.asyncio
    async def test_name_only_preserves_triggers_and_params(self):
        from gtm_mcp.write_tools import update_tag

        client, tags = _make_single_tag_client(_maven_tag())
        p1, p2 = _patched(client)
        with p1, p2:
            await update_tag(account_id="1", container_id="2", tag_id="100",
                             name="MT Action 1 (renamed)", workspace_id="113")

        body = tags.update.call_args.kwargs["body"]
        assert body["name"] == "MT Action 1 (renamed)"
        assert body["firingTriggerId"] == ["99", "452", "491"]
        assert body["parameter"] == [{"type": "template", "key": "url", "value": "u"}]
        assert "teardownTag" not in body

    @pytest.mark.asyncio
    async def test_empty_firing_trigger_ids_clears_them(self):
        from gtm_mcp.write_tools import update_tag

        client, tags = _make_single_tag_client(_yahoo_tag())
        p1, p2 = _patched(client)
        with p1, p2:
            await update_tag(account_id="1", container_id="2", tag_id="504",
                             firing_trigger_ids=[], workspace_id="113")

        body = tags.update.call_args.kwargs["body"]
        assert body["firingTriggerId"] == []

    @pytest.mark.asyncio
    async def test_html_param_and_firing_option_and_fingerprint(self):
        from gtm_mcp.write_tools import update_tag

        client, tags = _make_single_tag_client(_yahoo_tag())
        new_param = [{"type": "template", "key": "html", "value": "<script>gated</script>"}]
        p1, p2 = _patched(client)
        with p1, p2:
            await update_tag(account_id="1", container_id="2", tag_id="504",
                             parameter=new_param, tag_firing_option="oncePerLoad",
                             workspace_id="113")

        call = tags.update.call_args
        assert call.kwargs["fingerprint"] == "fp504"
        body = call.kwargs["body"]
        assert body["parameter"] == new_param
        assert body["tagFiringOption"] == "oncePerLoad"
