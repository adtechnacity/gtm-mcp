# `delete_tag` MCP tool — design

**Date:** 2026-05-11
**Branch:** `feature/pause-tag-tools`
**Status:** Approved, ready for implementation plan

## Motivation

The GTM MCP currently exposes `pause_tag` / `unpause_tag` but no way to delete a tag.
The user's saved workflow ("pause-first, consolidate not delete") uses pause as a
rollback marker. After a cooling period during which downstream tracking is verified,
paused tags should be deletable from this MCP rather than requiring a switch to the
GTM UI.

The `pause_tag` docstring already describes the intended workflow: "pause first,
monitor downstream tracking for a few days, then delete only if nothing breaks."
This tool closes that loop.

## Scope

- One new tool: `delete_tag`.
- Single-tag deletion. **No** batch variant in this change.
- No audit logging beyond the tool's return value.

## Tool spec

**Location:** `fastmcp_gtm_write_tools.py`, immediately below `unpause_tag`.

**Signature:**

```python
@mcp.tool()
async def delete_tag(
    account_id: str,
    container_id: str,
    tag_id: str,
    workspace_id: str = "1",
    force: bool = False,
) -> dict:
```

**Behavior:**

1. Validate `account_id`, `container_id`, `tag_id` via `_validate_ids`. On failure
   return `{status: "error", message: ...}` without any API calls.
2. Resolve workspace via `_resolve_workspace_parent`, build
   `path = f"{ws_parent}/tags/{tag_id}"`.
3. **Pause guard.** GET the tag. If `tag.get("paused") is not True` and
   `force is False`, return:
   ```python
   {
     "status": "error",
     "code": "not_paused",
     "message": (
         f"Refusing to delete unpaused tag '{name}' (id={tag_id}). "
         "Pause it first via pause_tag, or pass force=True."
     ),
     "tag_id": tag_id,
     "tag_name": name,
     "paused": bool(tag.get("paused", False)),
   }
   ```
   The structured `code` field lets callers branch without parsing the message.
4. Call `client.service.accounts().containers().workspaces().tags().delete(path=path)`
   via `_run`.
5. Return:
   ```python
   {
     "status": "success",
     "message": f"Tag '{name}' (id={tag_id}) deleted",
     "tag_id": tag_id,
     "tag_name": name,
   }
   ```
6. Wrap the whole body in the standard `try/except` returning
   `{status: "error", message: f"Failed to delete tag: {e}"}`.

**Docstring must mention:**
- Permanent within the workspace; takes effect at next `publish_gtm_container`.
- Workspace deletions can be discarded by reverting the workspace before publish.
- The pause guard and the `force` escape hatch.

## Why a pause-required guard

The user's feedback memory says pause is the rollback marker and deletes are
irreversible without restoring a prior container version. Encoding "tag must be
paused" into the tool itself means accidentally calling `delete_tag` on a live
tag is a no-op error instead of a destructive action. The cost is one extra GET
per delete — the same GET `_set_tag_paused` already performs.

`force=True` exists as a deliberate escape hatch for cases like deleting a tag
that was just created in this workspace and never published, where the pause
ritual is pointless.

## Tests

New file: `tests/test_delete_tag.py`. Reuse the `_make_mock_client` shape from
`tests/test_pause_tag.py`, extending it so `tags.delete()` is also mockable.

Required cases:

1. `force=False`, tag has `paused: True` → calls `tags().delete(path=...)` once,
   returns `status: "success"` with `tag_id` / `tag_name`.
2. `force=False`, tag has `paused: False` → returns `status: "error"`,
   `code: "not_paused"`; `delete` NOT called.
3. `force=False`, tag has no `paused` field (GTM omits it when falsy) → same as
   case 2.
4. `force=True`, tag has `paused: False` → calls `delete` once, returns success.
5. Invalid `tag_id` (`""`) → `status: "error"`, message mentions `tag_id`, no
   API calls.
6. Invalid `account_id` (`"bad"`) → `status: "error"`, message mentions
   `account_id`.

## Module bookkeeping

`fastmcp_gtm_write_tools.py` module docstring currently says "Registers 10
tools". Update count to 11 and append `delete_tag` to the tool list.

## Out of scope (deliberate)

- Batch delete (`delete_tags_batch`). Add only if a real need shows up.
- Auto-publish after delete. Stays a separate explicit step.
- Audit-log file. The MCP return value is the audit trail.
- Deletion of triggers / variables (variable delete already exists; trigger
  delete is a separate ask).

## File changes summary

- **Edit** `fastmcp_gtm_write_tools.py`: add `delete_tag`; bump module docstring.
- **New** `tests/test_delete_tag.py`: six tests above.
- No changes to `fastmcp_gtm_server.py`, helpers, or CLI.
