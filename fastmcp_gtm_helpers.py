"""
Shared server instance and helpers for GTM MCP tools.

Creates the FastMCP server, GTM client, and internal helpers used by both
read and write tool modules. Import from here — never instantiate separately.
"""
import asyncio
import copy
import logging
import sys
from datetime import datetime, timezone

# Redirect logging to stderr
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gtm-fastmcp-server")

from mcp.server import FastMCP

# Initialize the MCP server
mcp = FastMCP("gtm-fastmcp-server")

# GTM client initialization
gtm_client = None


def get_gtm_client():
    """Lazy initialization of GTM client"""
    global gtm_client
    if gtm_client is None:
        try:
            from gtm_client_fixed import GTMClient
            gtm_client = GTMClient()
            logger.info("GTM client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize GTM client: {e}")
            raise Exception(f"GTM authentication failed: {e}. Please ensure GOOGLE_APPLICATION_CREDENTIALS is set.")
    return gtm_client


async def _run(request):
    """Run a blocking Google API request in a thread pool."""
    result = await asyncio.to_thread(request.execute)
    if result is None:
        return {}
    return result


# Load GTM components
try:
    from gtm_components import GTMComponentTemplates, GTMWorkflowBuilder
    HAS_GTM_COMPONENTS = True
    logger.info("GTM components loaded successfully")
except ImportError as e:
    logger.error(f"Failed to load GTM components: {e}")
    HAS_GTM_COMPONENTS = False


# ---------------------------------------------------------------------------
# Internal helpers — shared logic extracted from tool functions
# ---------------------------------------------------------------------------

MAX_BATCH_SIZE = 50

# Cache for resolved workspace IDs: (account_id, container_id) → workspace_id
_workspace_cache: dict[tuple[str, str], str] = {}


async def _resolve_workspace_id(client, account_id: str, container_id: str, workspace_id: str) -> str:
    """Resolve workspace_id, auto-detecting if the caller passed the default '1'.

    GTM workspace IDs are not always '1'. When the default is used, this
    function lists the container's workspaces and returns the first one found.
    Results are cached per (account, container) pair for the server's lifetime.
    """
    if workspace_id != "1":
        if not str(workspace_id).strip().isdigit():
            raise ValueError(f"Invalid workspace_id: '{workspace_id}'. Must be a numeric string.")
        return workspace_id

    cache_key = (account_id, container_id)
    if cache_key in _workspace_cache:
        return _workspace_cache[cache_key]

    parent = f"accounts/{account_id}/containers/{container_id}"
    result = await _run(
        client.service.accounts().containers().workspaces().list(parent=parent)
    )
    workspaces = result.get("workspace", [])
    if not workspaces:
        logger.warning("No workspaces found for container %s; falling back to workspace_id='%s'", container_id, workspace_id)
        _workspace_cache[cache_key] = workspace_id
        return workspace_id

    # Check if workspace "1" actually exists
    ws_ids = [w.get("workspaceId") for w in workspaces if w.get("workspaceId")]
    if not ws_ids:
        logger.warning("No valid workspace IDs found for container %s", container_id)
        _workspace_cache[cache_key] = workspace_id
        return workspace_id
    if "1" in ws_ids:
        _workspace_cache[cache_key] = "1"
        return "1"

    # Use the first workspace found
    resolved = ws_ids[0]
    _workspace_cache[cache_key] = resolved
    logger.info(
        "Auto-resolved workspace_id to '%s' (container %s has no workspace '1')",
        resolved, container_id,
    )
    return resolved


async def _resolve_workspace_parent(client, account_id: str, container_id: str, workspace_id: str = "1") -> tuple[str, str]:
    """Resolve workspace ID and build the workspace parent path in one call."""
    ws_id = await _resolve_workspace_id(client, account_id, container_id, workspace_id)
    return ws_id, f"accounts/{account_id}/containers/{container_id}/workspaces/{ws_id}"


def _validate_gtm_id(value, name="ID"):
    """Validate that a GTM ID is a non-empty numeric string. Returns error message or None."""
    if not value or not str(value).strip().isdigit():
        return f"Invalid {name}: '{value}'. Must be a non-empty numeric string."
    return None


def _validate_ids(**ids):
    """Validate multiple GTM ID parameters. Returns first error or None."""
    for name, value in ids.items():
        error = _validate_gtm_id(value, name)
        if error:
            return error
    return None


async def _paginated_list(request_fn, result_key):
    """Fetch all pages from a GTM API list endpoint.

    request_fn → callable returning a Google API request object.
    result_key → key in response containing the list items (e.g. 'tag', 'variable').
    """
    items = []
    request = request_fn()
    while request is not None:
        result = await _run(request)
        items.extend(result.get(result_key, []))
        next_token = result.get('nextPageToken')
        if not next_token:
            break
        request = request_fn(pageToken=next_token)
    return items

_VALID_CONSENT_STATUSES = ("notSet", "notNeeded", "needed")


def _validate_consent_params(consent_status, consent_types):
    """Return error message string, or None if valid."""
    if consent_status not in _VALID_CONSENT_STATUSES:
        return f"Invalid consent_status '{consent_status}'. Must be 'notSet', 'notNeeded', or 'needed'."
    if consent_status == "needed" and not consent_types:
        return "consent_types is required when consent_status is 'needed'."
    return None


def _build_consent_settings(consent_status, consent_types):
    """Build GTM consentSettings dict from validated parameters."""
    settings = {"consentStatus": consent_status}
    if consent_status == "needed" and consent_types:
        settings["consentType"] = {
            "type": "list",
            "list": [{"type": "template", "value": ct} for ct in consent_types],
        }
    return settings


def _validate_trigger_filters(filters):
    """Validate user-provided trigger filter conditions.

    Each item must be a dict with string ``type`` and list ``parameter``,
    where each parameter is a dict with ``key``, ``value``, and ``type``.
    Returns an error message string, or None if valid. An empty list is valid
    (used to clear a filter list wholesale).
    """
    if not isinstance(filters, list):
        return "filters must be a list of condition dicts"
    for i, cond in enumerate(filters):
        if not isinstance(cond, dict):
            return f"filters[{i}] must be a dict"
        if not isinstance(cond.get("type"), str) or not cond["type"]:
            return f"filters[{i}].type must be a non-empty string"
        params = cond.get("parameter")
        if not isinstance(params, list) or not params:
            return f"filters[{i}].parameter must be a non-empty list"
        for j, p in enumerate(params):
            if not isinstance(p, dict) or not all(isinstance(p.get(k), str) for k in ("key", "value", "type")):
                return f"filters[{i}].parameter[{j}] must be a dict with string key/value/type"
    return None


def _filter_tuples_to_conditions(tuples):
    """Convert ``[{operator, lhs, rhs}, ...]`` to GTM Condition dicts.

    Each tuple becomes a Condition with ``type=operator`` and two template
    parameters (``arg0=lhs``, ``arg1=rhs``). This is the ergonomic form most
    callers want — they say "Page Path matchRegex /create" instead of hand-
    rolling the parameter list. Raises ValueError on bad input.
    """
    if not isinstance(tuples, list) or not tuples:
        raise ValueError("conditions must be a non-empty list")
    result = []
    for i, t in enumerate(tuples):
        if not isinstance(t, dict):
            raise ValueError(f"conditions[{i}] must be a dict with operator/lhs/rhs")
        operator = t.get("operator")
        lhs = t.get("lhs")
        rhs = t.get("rhs")
        for name, value in (("operator", operator), ("lhs", lhs), ("rhs", rhs)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"conditions[{i}].{name} must be a non-empty string")
        result.append({
            "type": operator,
            "parameter": [
                {"type": "template", "key": "arg0", "value": lhs},
                {"type": "template", "key": "arg1", "value": rhs},
            ],
        })
    return result


def _upsert_parameters(existing, updates):
    """Upsert GTM parameter dicts into ``existing`` by their ``key`` field.

    For each item in ``updates``, replaces the parameter sharing the same ``key``
    in ``existing`` or appends it. Returns a new list; inputs are not mutated.
    Raises ValueError on missing ``key``/``type`` or duplicate keys in updates.

    The caller is responsible for the inner shape of each update dict — value
    fields must match the GTM parameter ``type`` (``value`` for template/boolean/
    integer, ``list`` for list, ``map`` for map).
    """
    if not isinstance(updates, list):
        raise ValueError("updates must be a list of parameter dicts.")
    seen_keys = set()
    for u in updates:
        if not isinstance(u, dict):
            raise ValueError(f"Each update must be a dict, got {type(u).__name__}.")
        key = u.get("key")
        if not key or not isinstance(key, str):
            raise ValueError("Each update must have a non-empty string 'key'.")
        if not u.get("type"):
            raise ValueError(f"Update for key '{key}' is missing 'type'.")
        if key in seen_keys:
            raise ValueError(f"Duplicate key '{key}' in updates.")
        seen_keys.add(key)

    by_key = {p.get("key"): i for i, p in enumerate(existing or [])}
    result = list(existing or [])
    for u in updates:
        item = copy.deepcopy(u)
        idx = by_key.get(item["key"])
        if idx is None:
            by_key[item["key"]] = len(result)
            result.append(item)
        else:
            result[idx] = item
    return result


async def _create_datalayer_var(client, parent, name, key):
    """Create a single Data Layer Variable and return its result dict."""
    variable_body = {
        'name': name, 'type': 'v',
        'parameter': [
            {'key': 'dataLayerVersion', 'value': '2', 'type': 'integer'},
            {'key': 'setDefaultValue', 'value': 'false', 'type': 'boolean'},
            {'key': 'name', 'value': key, 'type': 'template'},
        ],
    }
    result = await _run(client.service.accounts().containers().workspaces().variables().create(
        parent=parent, body=variable_body))
    return {"name": name, "key": key, "variable_id": result.get('variableId')}


async def _update_one_tag(client, path, mutate_fn, extra_fields_fn=None):
    """Fetch, mutate, and update a single tag.

    Returns ("updated", entry) or ("skipped", entry).
    Raises on API errors — caller handles exceptions.
    """
    tag = await _run(client.service.accounts().containers().workspaces().tags().get(path=path))
    mutated = mutate_fn(tag)
    tag_id = path.rsplit("/", 1)[-1]
    if mutated is None:
        return "skipped", {"tag_id": tag_id, "tag_name": tag.get("name")}
    updated = await _run(client.service.accounts().containers().workspaces().tags().update(
        path=path, body=mutated, fingerprint=mutated.get("fingerprint")))
    entry = {"tag_id": tag_id, "tag_name": updated.get("name")}
    if extra_fields_fn:
        entry.update(extra_fields_fn(updated))
    return "updated", entry


async def _batch_update_tags(client, path_prefix, tag_ids, mutate_fn,
                             extra_fields_fn=None, skip_reason=None):
    """Fetch, mutate, and update multiple tags.

    path_prefix → "accounts/{id}/containers/{id}/workspaces/{id}" base path.
    mutate_fn(tag) → modified tag dict to proceed, or None to skip.
    extra_fields_fn(updated_tag) → dict of extra fields for updated entries (optional).
    skip_reason → static reason string added to skipped entries (optional).
    """
    if len(tag_ids) > MAX_BATCH_SIZE:
        return {"status": "error", "message": f"Batch size {len(tag_ids)} exceeds limit of {MAX_BATCH_SIZE}."}
    for tid in tag_ids:
        error = _validate_gtm_id(tid, "tag_id")
        if error:
            return {"status": "error", "message": error}
    results = {"updated": [], "skipped": [], "failed": []}
    for tag_id in tag_ids:
        try:
            category, entry = await _update_one_tag(
                client, f"{path_prefix}/tags/{tag_id}",
                mutate_fn, extra_fields_fn)
            if category == "skipped" and skip_reason:
                entry["reason"] = skip_reason
            results[category].append(entry)
        except Exception as e:
            results["failed"].append({"tag_id": tag_id, "error": str(e)})
    n_updated, n_failed, n_skipped = len(results["updated"]), len(results["failed"]), len(results["skipped"])
    results["status"] = "error" if n_failed and not n_updated else "partial" if n_failed else "success"
    results["summary"] = f"Updated {n_updated}/{len(tag_ids)} tags, skipped {n_skipped}, failed {n_failed}"
    return results


async def _append_trigger_to_tags_batch(
    client, path_prefix, tag_ids, trigger_id, *, field, label, skip_reason
):
    """Append a trigger ID to either ``firingTriggerId`` or ``blockingTriggerId`` across tags."""
    def append(tag):
        existing = tag.get(field, [])
        if trigger_id in existing:
            return None
        tag[field] = existing + [trigger_id]
        return tag
    return await _batch_update_tags(
        client, path_prefix, tag_ids, append,
        extra_fields_fn=lambda t: {label: t.get(field, [])},
        skip_reason=skip_reason,
    )


async def _remove_trigger_from_tags_batch(
    client, path_prefix, tag_ids, trigger_id, *, field, label, skip_reason
):
    """Remove a trigger ID from ``firingTriggerId`` or ``blockingTriggerId`` across tags."""
    def remove(tag):
        existing = tag.get(field, [])
        if trigger_id not in existing:
            return None
        tag[field] = [t for t in existing if t != trigger_id]
        return tag
    return await _batch_update_tags(
        client, path_prefix, tag_ids, remove,
        extra_fields_fn=lambda t: {label: t.get(field, [])},
        skip_reason=skip_reason,
    )


async def _set_triggers_on_tags_batch(
    client, path_prefix, tag_ids, trigger_ids, *, field, label, skip_reason
):
    """Replace the ``firingTriggerId`` or ``blockingTriggerId`` list with ``trigger_ids``."""
    new_list = list(trigger_ids)
    def set_list(tag):
        if tag.get(field, []) == new_list:
            return None
        tag[field] = new_list
        return tag
    return await _batch_update_tags(
        client, path_prefix, tag_ids, set_list,
        extra_fields_fn=lambda t: {label: t.get(field, [])},
        skip_reason=skip_reason,
    )


# ---------------------------------------------------------------------------
# Version history helpers — pure functions over ContainerVersion resources
# ---------------------------------------------------------------------------

# Volatile/identity keys that never represent a meaningful entity change.
_DIFF_IGNORED_KEYS = frozenset({
    "fingerprint", "path", "tagManagerUrl", "accountId", "containerId", "workspaceId",
})
_DIFF_MAX_STRING = 300
_DIFF_MAX_CHANGES = 40

# (result label, ContainerVersion array key, entity ID field)
_VERSION_ENTITY_SPECS = (
    ("tags", "tag", "tagId"),
    ("triggers", "trigger", "triggerId"),
    ("variables", "variable", "variableId"),
)


def _fingerprint_to_iso(fingerprint: object) -> str | None:
    """Convert a GTM fingerprint (milliseconds-since-epoch string) to ISO 8601 UTC.

    GTM stores a version's fingerprint as the millisecond timestamp of when it
    was stored — effectively the version's creation time. Returns None when the
    fingerprint is missing or unparseable.
    """
    if fingerprint is None or isinstance(fingerprint, bool):
        return None
    try:
        ms = int(str(fingerprint).strip())
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return dt.isoformat().replace("+00:00", "Z")


def _summarize_version(version: dict) -> dict:
    """Build a compact summary of a raw ContainerVersion resource.

    Full versions of large containers exceed 200KB; this keeps identity fields,
    entity counts, and slim per-entity listings only.
    """
    tags = version.get("tag", [])
    triggers = version.get("trigger", [])
    variables = version.get("variable", [])
    built_ins = version.get("builtInVariable", [])
    return {
        "containerVersionId": version.get("containerVersionId"),
        "name": version.get("name"),
        "description": version.get("description", ""),
        "fingerprint": version.get("fingerprint"),
        "fingerprint_datetime": _fingerprint_to_iso(version.get("fingerprint")),
        "tagManagerUrl": version.get("tagManagerUrl", ""),
        "deleted": version.get("deleted", False),
        "counts": {
            "tags": len(tags),
            "triggers": len(triggers),
            "variables": len(variables),
            "builtInVariables": len(built_ins),
        },
        "tags": [
            {
                "tagId": t.get("tagId"),
                "name": t.get("name"),
                "type": t.get("type"),
                "paused": t.get("paused", False),
                "firingTriggerId": t.get("firingTriggerId", []),
                "blockingTriggerId": t.get("blockingTriggerId", []),
                "consentSettings": t.get("consentSettings", {}),
            }
            for t in tags
        ],
        "triggers": [
            {"triggerId": t.get("triggerId"), "name": t.get("name"), "type": t.get("type")}
            for t in triggers
        ],
        "variables": [
            {"variableId": v.get("variableId"), "name": v.get("name"), "type": v.get("type")}
            for v in variables
        ],
        "builtInVariables": [b.get("name") for b in built_ins],
    }


def _truncate_diff_value(value: object) -> object:
    """Recursively truncate long strings in a diff value (HTML tag bodies are huge)."""
    if isinstance(value, str) and len(value) > _DIFF_MAX_STRING:
        return value[:_DIFF_MAX_STRING] + "… [truncated]"
    if isinstance(value, list):
        return [_truncate_diff_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _truncate_diff_value(v) for k, v in value.items()}
    return value


def _is_keyed_list(items: list) -> bool:
    """True when every entry is a dict with a unique, non-empty string ``key``.

    Duplicate or non-string keys disqualify the list — key-matching would
    silently collapse duplicates (false "no change") or raise on unhashable
    keys, so such lists fall back to indexed diffing.
    """
    keys = [i.get("key") for i in items if isinstance(i, dict)]
    return (
        len(keys) == len(items)
        and all(isinstance(k, str) and k for k in keys)
        and len(set(keys)) == len(keys)
    )


def _diff_entity_dicts(old: dict, new: dict, prefix: str = "") -> list[dict]:
    """Recursively diff two GTM entity dicts into ``[{"field", "from", "to"}, ...]``.

    Field paths are dotted (``consentSettings.consentStatus``), with list entries
    addressed by parameter key (``parameter[html]``) when entries carry GTM
    ``key`` fields, or by index (``firingTriggerId[0]``) otherwise. Volatile keys
    (fingerprint, path, tagManagerUrl, accountId, containerId, workspaceId) are
    ignored; long string values are truncated.
    """
    changes = []
    for key in sorted(set(old) | set(new)):
        if key in _DIFF_IGNORED_KEYS:
            continue
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val == new_val:
            continue
        changes.extend(_diff_values(old_val, new_val, f"{prefix}{key}"))
    return changes


def _diff_values(old_val: object, new_val: object, path: str) -> list[dict]:
    """Diff two values at ``path``, recursing into dicts and lists."""
    if isinstance(old_val, dict) and isinstance(new_val, dict):
        return _diff_entity_dicts(old_val, new_val, prefix=f"{path}.")
    if isinstance(old_val, list) and isinstance(new_val, list):
        if _is_keyed_list(old_val) and _is_keyed_list(new_val) and (old_val or new_val):
            return _diff_keyed_lists(old_val, new_val, path)
        return _diff_indexed_lists(old_val, new_val, path)
    return [{"field": path, "from": _truncate_diff_value(old_val), "to": _truncate_diff_value(new_val)}]


def _diff_keyed_lists(old_list: list, new_list: list, path: str) -> list[dict]:
    """Diff GTM parameter-style lists by matching entries on their ``key`` field."""
    changes = []
    old_by_key = {item["key"]: item for item in old_list}
    new_by_key = {item["key"]: item for item in new_list}
    for key in sorted(set(old_by_key) | set(new_by_key)):
        old_item = old_by_key.get(key)
        new_item = new_by_key.get(key)
        if old_item == new_item:
            continue
        entry_path = f"{path}[{key}]"
        if old_item is None or new_item is None:
            changes.append({
                "field": entry_path,
                "from": _truncate_diff_value(old_item),
                "to": _truncate_diff_value(new_item),
            })
        else:
            changes.extend(_diff_entity_dicts(old_item, new_item, prefix=f"{entry_path}."))
    return changes


def _diff_indexed_lists(old_list: list, new_list: list, path: str) -> list[dict]:
    """Diff two lists positionally; out-of-range entries compare against None."""
    changes = []
    for i in range(max(len(old_list), len(new_list))):
        old_item = old_list[i] if i < len(old_list) else None
        new_item = new_list[i] if i < len(new_list) else None
        if old_item == new_item:
            continue
        changes.extend(_diff_values(old_item, new_item, f"{path}[{i}]"))
    return changes


def _entity_sort_key(entity_id: object) -> tuple:
    """Sort numeric IDs numerically, everything else lexically after them."""
    s = str(entity_id)
    return (0, int(s), "") if s.isdigit() else (1, 0, s)


def _diff_versions(from_version: dict, to_version: dict) -> dict:
    """Compute the added/removed/changed structure between two ContainerVersions.

    Tags/triggers/variables are matched by their ID field, builtInVariables by
    name. ``changed`` entries carry per-field change lists from
    ``_diff_entity_dicts``, capped at ``_DIFF_MAX_CHANGES`` with a ``_truncated``
    marker when exceeded. Returns summary counts plus per-entity sections.
    """
    result = {"summary": {}}
    for label, array_key, id_field in _VERSION_ENTITY_SPECS:
        old_by_id = {e.get(id_field): e for e in from_version.get(array_key, [])}
        new_by_id = {e.get(id_field): e for e in to_version.get(array_key, [])}
        added, removed, changed = [], [], []
        for entity_id in sorted(set(old_by_id) | set(new_by_id), key=_entity_sort_key):
            old_entity = old_by_id.get(entity_id)
            new_entity = new_by_id.get(entity_id)
            if old_entity is None:
                added.append(_entity_brief(new_entity, id_field))
                continue
            if new_entity is None:
                removed.append(_entity_brief(old_entity, id_field))
                continue
            changes = _diff_entity_dicts(old_entity, new_entity)
            if not changes:
                continue
            if len(changes) > _DIFF_MAX_CHANGES:
                omitted = len(changes) - _DIFF_MAX_CHANGES
                changes = changes[:_DIFF_MAX_CHANGES] + [{
                    "field": "_truncated",
                    "from": None,
                    "to": f"{omitted} more changes omitted",
                }]
            entry = _entity_brief(new_entity, id_field)
            entry["changes"] = changes
            changed.append(entry)
        result[label] = {"added": added, "removed": removed, "changed": changed}
        result["summary"][label] = {
            "added": len(added), "removed": len(removed), "changed": len(changed),
        }

    old_names = {b.get("name") for b in from_version.get("builtInVariable", []) if b.get("name")}
    new_names = {b.get("name") for b in to_version.get("builtInVariable", []) if b.get("name")}
    biv_added = sorted(new_names - old_names)
    biv_removed = sorted(old_names - new_names)
    result["builtInVariables"] = {"added": biv_added, "removed": biv_removed}
    result["summary"]["builtInVariables"] = {
        "added": len(biv_added), "removed": len(biv_removed),
    }
    return result


def _entity_brief(entity: dict, id_field: str) -> dict:
    """Slim identity dict for an entity in a diff listing."""
    return {
        id_field: entity.get(id_field),
        "name": entity.get("name"),
        "type": entity.get("type"),
    }
