"""update_tags_triggers_batch, create_gtm_variable(datalayer_key), legacy aliases."""
import asyncio
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import tool_error
from gtm_mcp import legacy_tools
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
# Legacy aliases
# ---------------------------------------------------------------------------

class TestLegacyAliases:
    @pytest.mark.asyncio
    async def test_batch_alias_delegates_with_action_and_kind(self):
        with patch("gtm_mcp.legacy_tools.write_tools.update_tags_triggers_batch",
                   new=AsyncMock(return_value={"status": "success"})) as target:
            await legacy_tools.remove_blocking_trigger_from_tags_batch("1", "2", ["10"], "5")
        target.assert_awaited_once_with("1", "2", ["10"], "remove", ["5"], "blocking", None)

    @pytest.mark.asyncio
    async def test_create_js_variable_delegates(self):
        with patch("gtm_mcp.legacy_tools.write_tools.create_gtm_variable",
                   new=AsyncMock(return_value={"status": "success"})) as target:
            await legacy_tools.create_js_variable("1", "2", "JS - x", "function(){return 1}")
        target.assert_awaited_once_with(
            "1", "2", "JS - x", javascript="function(){return 1}", workspace_id=None)

    def test_descriptions_are_one_line_and_name_the_replacement(self):
        from gtm_mcp.server import mcp
        legacy = [t for t in asyncio.run(mcp.list_tools()) if hasattr(legacy_tools, t.name)]
        assert len(legacy) == 13
        for t in legacy:
            assert t.description.startswith("Deprecated: use ``"), t.name
            assert "\n" not in t.description.strip(), t.name

    def test_env_flag_hides_them(self):
        code = ("import asyncio; from gtm_mcp.server import mcp; "
                "print(len(asyncio.run(mcp.list_tools())))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={**os.environ, "GTM_MCP_LEGACY_TOOLS": "0"}, check=True)
        assert out.stdout.strip() == "27"
