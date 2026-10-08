"""Versions, workspaces, revert, get_gtm_trigger, find_gtm_references."""
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import tool_error
from gtm_mcp.helpers import _find_references, _matching_paths

WS = "accounts/1/containers/2/workspaces/54"


@contextmanager
def _patched(module, client):
    with patch(f"gtm_mcp.{module}.get_gtm_client", return_value=client), \
         patch(f"gtm_mcp.{module}._resolve_workspace_parent",
               new=AsyncMock(return_value=("54", WS))), \
         patch(f"gtm_mcp.{module}._forget_workspace", create=True) as forget:
        yield forget


def _returns(method, value):
    method.return_value.execute.return_value = value


# ---------------------------------------------------------------------------
# Pure reference search
# ---------------------------------------------------------------------------

class TestMatchingPaths:
    def test_addresses_parameters_by_key_and_lists_by_index(self):
        tag = {"name": "T", "parameter": [{"key": "html", "value": "<b>{{X}}</b>"}],
               "notes": "uses {{X}}", "list": ["a", "{{X}}"]}
        paths = _matching_paths(tag, lambda s: "{{X}}" in s)
        assert sorted(paths) == ["list[1]", "notes", "parameter[html].value"]

    def test_no_match(self):
        assert _matching_paths({"a": [1, None, {"b": "c"}]}, lambda s: s == "z") == []


TAGS = [
    {"tagId": "1", "name": "GA4", "firingTriggerId": ["10"], "blockingTriggerId": ["11"],
     "parameter": [{"key": "eventName", "value": "{{DLV - event}}"}]},
    {"tagId": "2", "name": "Pixel", "firingTriggerId": ["11"],
     "teardownTag": [{"tagName": "GA4"}]},
    {"tagId": "3", "name": "Unrelated", "firingTriggerId": ["12"]},
]
TRIGGERS = [
    {"triggerId": "10", "name": "All pages", "type": "pageview"},
    {"triggerId": "11", "name": "Bots", "type": "customEvent",
     "filter": [{"type": "equals", "parameter": [{"key": "arg0", "value": "{{DLV - event}}"}]}]},
    {"triggerId": "20", "name": "Group", "type": "triggerGroup",
     "parameter": [{"key": "triggerIds", "type": "list",
                    "list": [{"type": "triggerReference", "value": "11"}]}]},
]
VARIABLES = [
    {"variableId": "30", "name": "DLV - event", "type": "v"},
    {"variableId": "31", "name": "JS - is bot", "type": "jsm",
     "parameter": [{"key": "javascript", "value": "function(){return {{DLV - event}}=='bot'}"}]},
]


def _summary(refs):
    return {(r["kind"], r["id"]): r["where"] for r in refs}


class TestFindReferences:
    def test_trigger_firing_blocking_and_group(self):
        refs = _find_references("trigger", TRIGGERS[1], TAGS, TRIGGERS, VARIABLES)
        assert _summary(refs) == {
            ("tag", "1"): ["blockingTriggerId"],
            ("tag", "2"): ["firingTriggerId"],
            ("trigger", "20"): ["parameter[triggerIds].list[0].value"],
        }

    def test_variable_everywhere_but_itself(self):
        refs = _find_references("variable", VARIABLES[0], TAGS, TRIGGERS, VARIABLES)
        assert _summary(refs) == {
            ("tag", "1"): ["parameter[eventName].value"],
            ("trigger", "11"): ["filter[0].parameter[arg0].value"],
            ("variable", "31"): ["parameter[javascript].value"],
        }

    def test_tag_sequencing(self):
        refs = _find_references("tag", TAGS[0], TAGS, TRIGGERS, VARIABLES)
        assert _summary(refs) == {("tag", "2"): ["teardownTag"]}

    def test_unused_trigger_has_no_references(self):
        assert _find_references("trigger", {"triggerId": "99"}, TAGS, TRIGGERS, VARIABLES) == []


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

class TestReadTools:
    @pytest.mark.asyncio
    async def test_get_gtm_trigger(self):
        from gtm_mcp.read_tools import get_gtm_trigger
        client = MagicMock()
        triggers = client.service.accounts().containers().workspaces().triggers()
        _returns(triggers.get, TRIGGERS[1])
        with _patched("read_tools", client):
            result = await get_gtm_trigger("1", "2", "11")
        triggers.get.assert_called_with(path=f"{WS}/triggers/11")
        assert result["trigger"]["name"] == "Bots"

    @pytest.mark.asyncio
    async def test_find_gtm_references_wires_lists(self):
        from gtm_mcp.read_tools import find_gtm_references
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        _returns(ws.tags().list, {"tag": TAGS})
        _returns(ws.triggers().list, {"trigger": TRIGGERS})
        _returns(ws.variables().list, {"variable": VARIABLES})
        with _patched("read_tools", client):
            result = await find_gtm_references("1", "2", "variable", "30")
        assert result["target"] == {"kind": "variable", "id": "30", "name": "DLV - event"}
        assert result["total_references"] == 3

    @pytest.mark.asyncio
    async def test_find_gtm_references_built_in_trigger(self):
        from gtm_mcp.read_tools import find_gtm_references
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        _returns(ws.tags().list, {"tag": [{"tagId": "1", "firingTriggerId": ["2147479553"]}]})
        _returns(ws.triggers().list, {"trigger": TRIGGERS})
        _returns(ws.variables().list, {"variable": VARIABLES})
        with _patched("read_tools", client):
            result = await find_gtm_references("1", "2", "trigger", "2147479553")
        assert result["target"]["name"] == "(built-in trigger)"
        assert result["references"][0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_find_gtm_references_missing_variable(self):
        from gtm_mcp.read_tools import find_gtm_references
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        for coll, key in (("tags", "tag"), ("triggers", "trigger"), ("variables", "variable")):
            _returns(getattr(ws, coll)().list, {key: []})
        with _patched("read_tools", client):
            assert "not found" in await tool_error(find_gtm_references("1", "2", "variable", "99"))

    @pytest.mark.asyncio
    async def test_find_gtm_references_rejects_bad_kind(self):
        from gtm_mcp.read_tools import find_gtm_references
        assert "kind must be" in await tool_error(find_gtm_references("1", "2", "folder", "1"))


# ---------------------------------------------------------------------------
# Lifecycle tools
# ---------------------------------------------------------------------------

class TestVersions:
    @pytest.mark.asyncio
    async def test_create_version_does_not_publish(self):
        from gtm_mcp.lifecycle_tools import create_gtm_version
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        _returns(ws.create_version, {"containerVersion": {"containerVersionId": "40", "path": "v/40"},
                                     "newWorkspacePath": f"{WS[:-2]}55"})
        with _patched("lifecycle_tools", client) as forget:
            result = await create_gtm_version("1", "2", "draft", "notes")
        ws.create_version.assert_called_once_with(path=WS, body={"name": "draft", "notes": "notes"})
        client.service.accounts().containers().versions().publish.assert_not_called()
        forget.assert_called_once_with("1", "2")
        assert result["version_id"] == "40"

    @pytest.mark.asyncio
    async def test_create_version_reports_merge_conflict(self):
        from gtm_mcp.lifecycle_tools import create_gtm_version
        client = MagicMock()
        _returns(client.service.accounts().containers().workspaces().create_version,
                 {"syncStatus": {"mergeConflict": True}})
        with _patched("lifecycle_tools", client):
            assert "mergeConflict" in await tool_error(create_gtm_version("1", "2", "draft"))

    @pytest.mark.asyncio
    async def test_publish_version_targets_that_version(self):
        from gtm_mcp.lifecycle_tools import publish_gtm_version
        client = MagicMock()
        versions = client.service.accounts().containers().versions()
        _returns(versions.publish, {"containerVersion": {"containerVersionId": "37"}})
        with _patched("lifecycle_tools", client):
            result = await publish_gtm_version("1", "2", "37")
        versions.publish.assert_called_once_with(path="accounts/1/containers/2/versions/37")
        assert result["version_id"] == "37"

    @pytest.mark.asyncio
    async def test_publish_version_compiler_error(self):
        from gtm_mcp.lifecycle_tools import publish_gtm_version
        client = MagicMock()
        _returns(client.service.accounts().containers().versions().publish, {"compilerError": True})
        with _patched("lifecycle_tools", client):
            assert "compiler errors" in await tool_error(publish_gtm_version("1", "2", "37"))

    @pytest.mark.asyncio
    async def test_publish_version_validates_id(self):
        from gtm_mcp.lifecycle_tools import publish_gtm_version
        assert "version_id" in await tool_error(publish_gtm_version("1", "2", "live"))


class TestWorkspaces:
    @pytest.mark.asyncio
    async def test_create_workspace(self):
        from gtm_mcp.lifecycle_tools import create_gtm_workspace
        client = MagicMock()
        ws = client.service.accounts().containers().workspaces()
        _returns(ws.create, {"workspaceId": "60", "name": "Kem draft"})
        with _patched("lifecycle_tools", client) as forget:
            result = await create_gtm_workspace("1", "2", "Kem draft")
        ws.create.assert_called_once_with(parent="accounts/1/containers/2",
                                          body={"name": "Kem draft", "description": ""})
        forget.assert_called_once_with("1", "2")
        assert result["workspace_id"] == "60"

    @pytest.mark.asyncio
    async def test_create_workspace_needs_name(self):
        from gtm_mcp.lifecycle_tools import create_gtm_workspace
        assert "name" in await tool_error(create_gtm_workspace("1", "2", " "))

    @pytest.mark.asyncio
    async def test_status_flattens_changes_and_conflicts(self):
        from gtm_mcp.lifecycle_tools import get_gtm_workspace_status
        client = MagicMock()
        _returns(client.service.accounts().containers().workspaces().getStatus, {
            "workspaceChange": [
                {"tag": {"tagId": "1", "name": "GA4"}, "changeStatus": "updated"},
                {"folder": {"name": "Ads"}, "changeStatus": "added"},
            ],
            "mergeConflict": [{"entityInWorkspace": {"trigger": {"triggerId": "11", "name": "Bots"},
                                                     "changeStatus": "updated"},
                               "entityInBaseVersion": {"trigger": {"triggerId": "11", "name": "Bots"},
                                                       "changeStatus": "deleted"}}],
        })
        with _patched("lifecycle_tools", client):
            result = await get_gtm_workspace_status("1", "2")
        assert result["changes"] == [
            {"kind": "tag", "id": "1", "name": "GA4", "status": "updated"},
            {"kind": "folder", "name": "Ads", "status": "added"},
        ]
        assert result["merge_conflicts"][0]["base_version"]["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_sync_with_conflicts_is_partial(self):
        from gtm_mcp.lifecycle_tools import sync_gtm_workspace
        client = MagicMock()
        _returns(client.service.accounts().containers().workspaces().sync, {
            "syncStatus": {"mergeConflict": True},
            "mergeConflict": [{"entityInWorkspace": {"tag": {"tagId": "1"}}}],
        })
        with _patched("lifecycle_tools", client):
            result = await sync_gtm_workspace("1", "2")
        assert result["status"] == "partial"
        assert len(result["merge_conflicts"]) == 1

    @pytest.mark.asyncio
    async def test_sync_error(self):
        from gtm_mcp.lifecycle_tools import sync_gtm_workspace
        client = MagicMock()
        _returns(client.service.accounts().containers().workspaces().sync,
                 {"syncStatus": {"syncError": True}})
        with _patched("lifecycle_tools", client):
            assert "failed" in await tool_error(sync_gtm_workspace("1", "2"))


class TestRevert:
    @pytest.mark.parametrize("kind, collection, key", [
        ("tag", "tags", "tag"), ("trigger", "triggers", "trigger"), ("variable", "variables", "variable"),
    ])
    @pytest.mark.asyncio
    async def test_reverts_the_right_collection(self, kind, collection, key):
        from gtm_mcp.lifecycle_tools import revert_gtm_entity
        client = MagicMock()
        resource = getattr(client.service.accounts().containers().workspaces(), collection)()
        _returns(resource.revert, {key: {"name": "Restored"}})
        with _patched("lifecycle_tools", client):
            result = await revert_gtm_entity("1", "2", kind, "7")
        resource.revert.assert_called_once_with(path=f"{WS}/{collection}/7")
        assert result["name"] == "Restored"
        assert "reverted" in result["message"]

    @pytest.mark.asyncio
    async def test_new_entity_is_removed(self):
        from gtm_mcp.lifecycle_tools import revert_gtm_entity
        client = MagicMock()
        _returns(client.service.accounts().containers().workspaces().tags().revert, {})
        with _patched("lifecycle_tools", client):
            result = await revert_gtm_entity("1", "2", "tag", "7")
        assert "removed" in result["message"]

    @pytest.mark.asyncio
    async def test_bad_kind(self):
        from gtm_mcp.lifecycle_tools import revert_gtm_entity
        assert "kind must be" in await tool_error(revert_gtm_entity("1", "2", "folder", "7"))
