# `delete_tag` MCP Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `delete_tag` MCP tool that permanently removes a GTM tag from a workspace, with a pause-required guard and `force=True` escape hatch.

**Architecture:** Mirror the shape of `pause_tag` (validation → resolve workspace → fetch tag → mutate) and `delete_gtm_variable` (call `tags().delete(path=...)`). The new tool fetches the tag first to enforce the pause guard, then calls the GTM API's delete endpoint. Returns a structured dict identical in shape to other write tools.

**Tech Stack:** Python 3, FastMCP, `googleapiclient` (Tag Manager API v2), `pytest` + `pytest-asyncio`, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-05-11-delete-tag-design.md`

---

## File Structure

- **Modify** `fastmcp_gtm_write_tools.py` — add `delete_tag` tool function below `unpause_tag`; bump module docstring tool count.
- **Create** `tests/test_delete_tag.py` — six pytest-asyncio tests covering the happy path, pause guard, force override, and input validation.

No other files change. The tool uses existing helpers (`_validate_ids`, `_resolve_workspace_parent`, `_run`) and the existing FastMCP `mcp` instance.

---

## Task 1: Happy-path test scaffolding + minimal implementation

**Files:**
- Create: `tests/test_delete_tag.py`
- Modify: `fastmcp_gtm_write_tools.py` (append `delete_tag` after `unpause_tag`, around line 607)

- [ ] **Step 1: Create the test file with a shared mock helper and the first failing test**

Write to `tests/test_delete_tag.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_delete_tag.py -v`
Expected: FAIL with `ImportError: cannot import name 'delete_tag'`.

- [ ] **Step 3: Append minimal `delete_tag` implementation**

In `fastmcp_gtm_write_tools.py`, after the `unpause_tag` function (currently ends around line 606), add:

```python


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@mcp.tool()
async def delete_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str = "1",
    force: bool = False,
) -> dict:
    """Delete a GTM tag from a workspace.

    Permanent within the workspace — takes effect at the next
    `publish_gtm_container`. Unpublished workspace deletes can be undone by
    discarding workspace changes in the GTM UI.

    Refuses to delete tags that are not paused unless `force=True`. The
    pause-first workflow exists so the paused-but-still-in-workspace state
    can be monitored for downstream impact before deletion makes it
    irreversible.

    Args:
        account_id: GTM Account ID
        container_id: GTM Container ID
        tag_id: The tag ID to delete
        workspace_id: GTM Workspace ID (auto-detected if omitted)
        force: If True, delete even when the tag is not paused. Default False.
    """
    try:
        error = _validate_ids(account_id=account_id, container_id=container_id, tag_id=tag_id)
        if error:
            return {"status": "error", "message": error}

        client = get_gtm_client()
        _, ws_parent = await _resolve_workspace_parent(client, account_id, container_id, workspace_id)
        path = f"{ws_parent}/tags/{tag_id}"

        tag = await _run(
            client.service.accounts().containers().workspaces().tags().get(path=path)
        )
        name = tag.get("name")

        await _run(
            client.service.accounts().containers().workspaces().tags().delete(path=path)
        )
        return {
            "status": "success",
            "message": f"Tag '{name}' (id={tag_id}) deleted",
            "tag_id": tag_id,
            "tag_name": name,
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to delete tag: {str(e)}"}
```

Note: this is intentionally missing the pause guard. Task 2 adds it via the next failing test. The GET-before-delete is already wired because we need the tag's `name` for the response and (next task) the `paused` field.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_delete_tag.py -v`
Expected: PASS — 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_delete_tag.py fastmcp_gtm_write_tools.py
git commit -m "feat: add delete_tag tool (happy path)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Pause guard

**Files:**
- Modify: `tests/test_delete_tag.py` (append new test class)
- Modify: `fastmcp_gtm_write_tools.py` (add guard inside `delete_tag`)

- [ ] **Step 1: Append the failing pause-guard test class**

Append to `tests/test_delete_tag.py`:

```python


class TestDeleteTagPauseGuard:
    @pytest.mark.asyncio
    async def test_unpaused_tag_refuses_delete_without_force(self):
        from fastmcp_gtm_write_tools import delete_tag

        tag = {"name": "Live Tag", "tagId": "100",
               "fingerprint": "fp1", "paused": False}
        client, tags = _make_mock_client(tag)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await delete_tag(
                account_id="1", container_id="2", tag_id="100"
            )

        assert result["status"] == "error"
        assert result["code"] == "not_paused"
        assert result["tag_id"] == "100"
        assert result["tag_name"] == "Live Tag"
        assert result["paused"] is False
        assert "pause_tag" in result["message"]
        assert "force=True" in result["message"]
        tags.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_tag_missing_paused_field_is_treated_as_unpaused(self):
        """GTM omits the `paused` field when False — must not delete."""
        from fastmcp_gtm_write_tools import delete_tag

        tag = {"name": "Live Tag", "tagId": "100", "fingerprint": "fp1"}
        client, tags = _make_mock_client(tag)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await delete_tag(
                account_id="1", container_id="2", tag_id="100"
            )

        assert result["status"] == "error"
        assert result["code"] == "not_paused"
        assert result["paused"] is False
        tags.delete.assert_not_called()
```

- [ ] **Step 2: Run the new tests to verify both fail**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_delete_tag.py::TestDeleteTagPauseGuard -v`
Expected: Both tests FAIL (the implementation currently deletes regardless of `paused`).

- [ ] **Step 3: Insert the pause guard into `delete_tag`**

In `fastmcp_gtm_write_tools.py`, inside `delete_tag`, replace the block that fetches the tag and immediately calls delete with this version (adds the guard between GET and DELETE):

```python
        tag = await _run(
            client.service.accounts().containers().workspaces().tags().get(path=path)
        )
        name = tag.get("name")
        paused = bool(tag.get("paused", False))

        if not paused and not force:
            return {
                "status": "error",
                "code": "not_paused",
                "message": (
                    f"Refusing to delete unpaused tag '{name}' (id={tag_id}). "
                    "Pause it first via pause_tag, or pass force=True."
                ),
                "tag_id": tag_id,
                "tag_name": name,
                "paused": paused,
            }

        await _run(
            client.service.accounts().containers().workspaces().tags().delete(path=path)
        )
```

- [ ] **Step 4: Run the full test file to verify all three tests pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_delete_tag.py -v`
Expected: PASS — 3 tests pass (happy path + both guard tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_delete_tag.py fastmcp_gtm_write_tools.py
git commit -m "feat: add pause-required guard to delete_tag

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `force=True` override

**Files:**
- Modify: `tests/test_delete_tag.py` (append new test method)

- [ ] **Step 1: Append the force-override test**

Append inside the existing `TestDeleteTagPauseGuard` class in `tests/test_delete_tag.py`:

```python

    @pytest.mark.asyncio
    async def test_force_true_deletes_unpaused_tag(self):
        from fastmcp_gtm_write_tools import delete_tag

        tag = {"name": "Live Tag", "tagId": "100",
               "fingerprint": "fp1", "paused": False}
        client, tags = _make_mock_client(tag)

        with patch("fastmcp_gtm_write_tools.get_gtm_client", return_value=client), \
             patch("fastmcp_gtm_write_tools._resolve_workspace_parent",
                   new=AsyncMock(return_value=("1", "accounts/1/containers/2/workspaces/1"))):
            result = await delete_tag(
                account_id="1", container_id="2", tag_id="100", force=True
            )

        assert result["status"] == "success"
        assert result["tag_id"] == "100"
        assert result["tag_name"] == "Live Tag"
        tags.delete.assert_called_once()
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_delete_tag.py -v`
Expected: PASS — 4 tests pass. (No implementation change needed; the guard from Task 2 already short-circuits on `force=True`. This test locks in that behavior.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_delete_tag.py
git commit -m "test: lock in force=True override for delete_tag

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Input validation tests

**Files:**
- Modify: `tests/test_delete_tag.py` (append new test class)

- [ ] **Step 1: Append the validation test class**

Append to `tests/test_delete_tag.py`:

```python


class TestDeleteTagValidation:
    @pytest.mark.asyncio
    async def test_invalid_account_id_returns_error(self):
        from fastmcp_gtm_write_tools import delete_tag

        result = await delete_tag(account_id="bad", container_id="2", tag_id="100")
        assert result["status"] == "error"
        assert "account_id" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_tag_id_returns_error(self):
        from fastmcp_gtm_write_tools import delete_tag

        result = await delete_tag(account_id="1", container_id="2", tag_id="")
        assert result["status"] == "error"
        assert "tag_id" in result["message"]
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest tests/test_delete_tag.py -v`
Expected: PASS — 6 tests pass. (`_validate_ids` already enforces these; the tests pin that behavior to `delete_tag` specifically.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_delete_tag.py
git commit -m "test: add input validation tests for delete_tag

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Module bookkeeping + final verification

**Files:**
- Modify: `fastmcp_gtm_write_tools.py` (module docstring at the top, lines 1–8)

- [ ] **Step 1: Update the module docstring**

In `fastmcp_gtm_write_tools.py`, replace the current docstring:

```python
"""
Write MCP tools for Google Tag Manager.

Registers 10 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
publish_gtm_container, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch, pause_tag, unpause_tag.
"""
```

with:

```python
"""
Write MCP tools for Google Tag Manager.

Registers 11 tools on the shared ``mcp`` instance from fastmcp_gtm_helpers:
create_tag, create_trigger, create_datalayer_variable, create_datalayer_variables_batch,
publish_gtm_container, update_tag_consent_settings, update_tags_consent_settings_batch,
add_firing_trigger_to_tags_batch, pause_tag, unpause_tag, delete_tag.
"""
```

- [ ] **Step 2: Run the full test suite to make sure nothing else regressed**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run pytest -v`
Expected: PASS — all previously-passing tests plus the 6 new `test_delete_tag.py` tests pass. If any unrelated test fails, stop and investigate.

- [ ] **Step 3: Sanity-check the tool is registered on the MCP**

Run: `cd /Users/kemberlymiliano/gtm-mcp && uv run python -c "import fastmcp_gtm_server; import fastmcp_gtm_write_tools; from fastmcp_gtm_helpers import mcp; import asyncio; tools = asyncio.run(mcp.get_tools()); print('delete_tag' in tools)"`
Expected: `True`

If the snippet errors because `get_tools()` is not the right accessor on the installed FastMCP version, fall back to: `uv run python -c "import fastmcp_gtm_write_tools; print([t for t in dir(fastmcp_gtm_write_tools) if 'delete' in t.lower()])"` and confirm `delete_tag` appears.

- [ ] **Step 4: Commit**

```bash
git add fastmcp_gtm_write_tools.py
git commit -m "chore: bump module tool count to 11 for delete_tag

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:**
  - Signature with `force=False` default → Task 1.
  - `_validate_ids` validation → Task 1 (impl) + Task 4 (tests).
  - `_resolve_workspace_parent` + path build → Task 1.
  - Pause guard with structured `code: "not_paused"` → Task 2.
  - `tags().delete(path=...)` call → Task 1.
  - Success / error return shapes → Task 1 + Task 2.
  - `try/except` wrapping with `"Failed to delete tag: ..."` → Task 1.
  - Docstring mentions permanence, publish-to-apply, undo via discard, guard, force → Task 1.
  - Six required test cases (paused-deletes / unpaused-refuses / missing-paused-treated-as-unpaused / force-overrides / invalid-tag-id / invalid-account-id) → Tasks 1, 2, 3, 4.
  - Module docstring updated 10 → 11 with `delete_tag` listed → Task 5.

- **Placeholder scan:** No TBDs, no "implement appropriate ...", no "similar to Task N". Every code block is complete.

- **Type / name consistency:**
  - `delete_tag` signature is identical across all tasks.
  - `_make_mock_client` helper is defined once in Task 1 and reused by name in Tasks 2–4.
  - Field names in returns (`tag_id`, `tag_name`, `paused`, `code`, `message`, `status`) match between implementation and assertions.
  - Resource path `accounts/1/containers/2/workspaces/<id>/tags/<id>` is consistent.

No issues found.
