"""update_tags_triggers_batch, create_gtm_variable(datalayer_key), update_tag no-op."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import tool_error
from gtm_mcp.helpers import _modify_tag_triggers_batch

WS = "accounts/1/containers/2/workspaces/54"


def _tags_client(tags_by_id):
    """Mock client whose tags().get/update read and echo ``tags_by_id``."""
    client = MagicMock()
    tags = client.service.accounts().containers().workspaces().tags()
    tags.get.side_effect = lambda path: MagicMock(
        execute=MagicMock(return_value=dict(tags_by_id[path.rsplit("/", 1)[-1]])))
    tags.update.side_effect = lambda path, body, fingerprint: MagicMock(
        execute=MagicMock(return_value=body))
    return client, tags


def _written(tags, field):
    return {c.kwargs["path"].rsplit("/", 1)[-1]: c.kwargs["body"][field]
            for c in tags.update.call_args_list}


# ---------------------------------------------------------------------------
# _modify_tag_triggers_batch
# ---------------------------------------------------------------------------

class TestModifyTagTriggers:
    TAGS = {
        "10": {"name": "A", "firingTriggerId": ["1", "2"]},
        "11": {"name": "B", "firingTriggerId": ["2"]},
        "12": {"name": "C"},
    }

    async def _run(self, action, ids, field="firingTriggerId"):
        client, tags = _tags_client(self.TAGS)
        result = await _modify_tag_triggers_batch(
            client, WS, list(self.TAGS), ids, action=action, field=field)
        return result, _written(tags, field)

    @pytest.mark.asyncio
    async def test_add_appends_missing_only_and_dedupes(self):
        result, written = await self._run("add", ["2", "3", "3"])
        assert written == {"10": ["1", "2", "3"], "11": ["2", "3"], "12": ["2", "3"]}
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_add_skips_tags_that_already_have_them(self):
        result, written = await self._run("add", ["2"])
        assert written == {"12": ["2"]}
        assert [s["tag_id"] for s in result["skipped"]] == ["10", "11"]

    @pytest.mark.asyncio
    async def test_remove_keeps_others(self):
        _, written = await self._run("remove", ["2"])
        assert written == {"10": ["1"], "11": []}

    @pytest.mark.asyncio
    async def test_set_replaces_and_skips_equal(self):
        _, written = await self._run("set", ["2"])
        assert written == {"10": ["2"], "12": ["2"]}

    @pytest.mark.asyncio
    async def test_blocking_field_leaves_firing_alone(self):
        _, written = await self._run("add", ["9"], field="blockingTriggerId")
        assert written == {"10": ["9"], "11": ["9"], "12": ["9"]}


# ---------------------------------------------------------------------------
# update_tags_triggers_batch (tool)
# ---------------------------------------------------------------------------

async def _call_triggers_tool(**kwargs):
    from gtm_mcp.write_tools import update_tags_triggers_batch
    client, tags = _tags_client({"10": {"name": "A", "blockingTriggerId": ["5"]}})
    with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
         patch("gtm_mcp.write_tools._resolve_workspace_parent",
               new=AsyncMock(return_value=("54", WS))):
        result = await update_tags_triggers_batch(account_id="1", container_id="2", **kwargs)
    return result, tags


class TestUpdateTagsTriggersBatch:
    @pytest.mark.asyncio
    async def test_kind_blocking_writes_blocking_list(self):
        result, tags = await _call_triggers_tool(
            tag_ids=["10"], action="remove", trigger_ids=["5"], kind="blocking")
        assert _written(tags, "blockingTriggerId") == {"10": []}
        assert result["updated"][0]["blockingTriggerId"] == []

    @pytest.mark.asyncio
    async def test_set_accepts_empty_list(self):
        result, tags = await _call_triggers_tool(tag_ids=["10"], action="set", trigger_ids=[])
        assert result["status"] == "success"

    @pytest.mark.parametrize("kwargs, fragment", [
        ({"action": "replace", "trigger_ids": ["1"]}, "action must be"),
        ({"action": "add", "trigger_ids": ["1"], "kind": "exception"}, "kind must be"),
        ({"action": "add", "trigger_ids": []}, "can't be empty"),
        ({"action": "add", "trigger_ids": ["abc"]}, "trigger_ids[0]"),
        ({"action": "add", "trigger_ids": "1"}, "must be a list"),
    ])
    @pytest.mark.asyncio
    async def test_invalid_input_never_touches_tags(self, kwargs, fragment):
        from gtm_mcp.write_tools import update_tags_triggers_batch
        client, tags = _tags_client({})
        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client):
            message = await tool_error(update_tags_triggers_batch(
                account_id="1", container_id="2", tag_ids=["10"], **kwargs))
        assert fragment in message
        tags.get.assert_not_called()


# ---------------------------------------------------------------------------
# create_gtm_variable(datalayer_key=...)
# ---------------------------------------------------------------------------

class TestCreateDatalayerShortcut:
    async def _create(self, **kwargs):
        from gtm_mcp.write_tools import create_gtm_variable
        client = MagicMock()
        variables = client.service.accounts().containers().workspaces().variables()
        variables.create.side_effect = lambda parent, body: MagicMock(
            execute=MagicMock(return_value={**body, "variableId": "7"}))
        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", WS))):
            return await create_gtm_variable(account_id="1", container_id="2", **kwargs), variables

    @pytest.mark.asyncio
    async def test_builds_data_layer_variable(self):
        result, variables = await self._create(name="DLV - order_id", datalayer_key="order_id")
        body = variables.create.call_args.kwargs["body"]
        assert body["type"] == "v"
        assert {"key": "name", "value": "order_id", "type": "template"} in body["parameter"]
        assert result["variable_type"] == "v"

    @pytest.mark.parametrize("kwargs, fragment", [
        ({"datalayer_key": "k", "javascript": "function(){}"}, "mutually exclusive"),
        ({"datalayer_key": "k", "variable_type": "c"}, "requires type 'v'"),
        ({"datalayer_key": " "}, "non-empty"),
        ({"javascript": ""}, "non-empty"),
    ])
    @pytest.mark.asyncio
    async def test_rejects_bad_shortcuts(self, kwargs, fragment):
        message = await tool_error(self._create(name="x", **kwargs))
        assert fragment in message


# ---------------------------------------------------------------------------
# Legacy aliases keep their old response shapes
# ---------------------------------------------------------------------------

class TestUpdateTagNoop:
    @pytest.mark.asyncio
    async def test_unchanged_values_write_nothing(self):
        from gtm_mcp.write_tools import update_tag
        client, tags = _tags_client({"10": {"name": "A", "paused": True, "notes": "n"}})
        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", WS))):
            result = await update_tag("1", "2", "10", paused=True, notes="n")
        assert result["status"] == "noop"
        tags.update.assert_not_called()

    @pytest.mark.parametrize("before, paused", [(False, True), (True, False)])
    @pytest.mark.asyncio
    async def test_pause_and_unpause_preserve_other_fields(self, before, paused):
        from gtm_mcp.write_tools import update_tag
        tag = {"name": "A", "paused": before, "firingTriggerId": ["5"], "parameter": [{"key": "k"}]}
        client, tags = _tags_client({"10": tag})
        with patch("gtm_mcp.write_tools.get_gtm_client", return_value=client), \
             patch("gtm_mcp.write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("54", WS))):
            result = await update_tag("1", "2", "10", paused=paused)
        assert result["status"] == "success"
        assert tags.update.call_args.kwargs["body"] == {**tag, "paused": paused}
