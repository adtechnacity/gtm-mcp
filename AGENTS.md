# AGENTS.md — AI Agent Reference for GTM MCP Server

## Architecture

Package `src/gtm_mcp/`:

| Module           | Role                                                                                     |
| ---------------- | ---------------------------------------------------------------------------------------- |
| `server.py`      | Entry point (`mcp-gtm-server`) — imports the tool modules, picks stdio/HTTP transport    |
| `read_tools.py`  | Discovery, read, and version-history tools (+ `delete_gtm_variable`, historical)         |
| `write_tools.py` | Create / update / delete / publish tools                                                 |
| `helpers.py`     | Shared `mcp` instance, lazy GTM client, workspace resolution, validation, batch + diff helpers |
| `client.py`      | `GTMClient` — service account or OAuth auth, builds the `tagmanager` v2 service          |
| `cli.py`         | `gtm-cli` — read-only subcommands, prints JSON to stdout                                 |

Tools register with `@gtm_tool("<failure prefix>")` (helpers), which turns
returned `{"status": "error"}` dicts and exceptions into MCP errors. They call
`client.service` (googleapiclient) through `helpers._run`, which runs the
blocking request in a thread on that thread's own connection (`httplib2.Http`
isn't thread-safe). Root `fastmcp_gtm_server.py` is
only a back-compat launcher for existing MCP configs.

## ID Hierarchy

GTM uses a strict hierarchy: **Account > Container > Workspace > Resource**

```
accounts/{accountId}
  └── containers/{containerId}
        └── workspaces/{workspaceId}
              ├── tags/{tagId}
              ├── triggers/{triggerId}
              └── variables/{variableId}
```

Most tools require `account_id` + `container_id`. Workspace-scoped tools take an
optional `workspace_id`; when omitted they use the workspace named "Default
Workspace" (its ID changes after each publish from it), or the only workspace.
With several workspaces and no default they fail and list the IDs. The
resolution is cached 5 minutes and dropped on publish. `"1"` (the old default)
still works and keeps workspace 1 if it exists.

## Errors

Failures are MCP errors (`isError: true`), with text like
`Failed to update tag: HTTP 404: Not found or permission denied.` Successful
results are dicts with `status: "success"`; batch tools may return
`status: "partial"` with per-item `updated` / `skipped` / `failed` lists, and
pause/unpause return `status: "noop"` when nothing changed.

## Environment Variables

| Variable                         | Default  | Description                                                        |
| -------------------------------- | -------- | ------------------------------------------------------------------ |
| `GOOGLE_APPLICATION_CREDENTIALS` | —        | Service account JSON key path (takes precedence)                   |
| `GOOGLE_OAUTH_CLIENT_SECRET`     | —        | OAuth Desktop App client secret path; token cached in `~/.gtm-mcp/token.json` |
| `GCP_SA_JSON`                    | —        | Container only: SA JSON content, written to disk by `entrypoint.sh` |
| `MCP_TRANSPORT`                  | `stdio`  | `stdio`, `sse`, or `streamable-http`                               |
| `HOST` / `PORT`                  | `127.0.0.1` / `8000` | HTTP bind address                                       |
| `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` | — | Comma-separated; unset disables DNS-rebinding protection (HTTP only) |

One of the two credential variables is required. Scopes requested:
`tagmanager.readonly`, `tagmanager.edit.containers`, `tagmanager.publish`.

## Implemented Tools

### Discovery

| Tool                  | Description                                                   |
| --------------------- | ------------------------------------------------------------- |
| `test_gtm_connection` | Verify service account credentials work by listing containers |
| `list_gtm_accounts`   | List all accessible GTM accounts                              |
| `list_gtm_containers` | List containers in an account                                 |
| `list_gtm_workspaces` | List workspaces in a container                                |

### Reading

| Tool                 | Description                         |
| -------------------- | ----------------------------------- |
| `list_gtm_tags`      | List all tags with consent settings |
| `list_gtm_triggers`  | List all triggers with filters      |
| `list_gtm_variables` | List all variables                  |
| `get_gtm_tag`        | Get full tag details by ID          |
| `get_gtm_variable`   | Get full variable details by ID (JS source for `jsm`) |

### Version History

| Tool                          | Description                                                                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_gtm_container_versions` | List a container's version headers (IDs are monotonic; no timestamps — date a version via `get_gtm_container_version`)                            |
| `get_gtm_container_version`   | Summarized snapshot of one version (counts + slim entity listings + `fingerprint_datetime`); accepts `version_id="live"`                          |
| `get_gtm_live_version`        | Summarized snapshot of the currently published version                                                                                            |
| `diff_gtm_container_versions` | Server-side field-level diff between two versions (numeric IDs or `"live"`) — added/removed/changed tags, triggers, variables, built-in variables |

### Creating

| Tool                               | Description                                                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `create_tag`                       | Create any tag type (GA4, Custom HTML, Facebook Pixel, Google Ads, etc.)                                          |
| `create_trigger`                   | Create any GTM trigger type (customEvent, pageview, init, domReady, etc.); optional `filters` adds AND conditions |
| `create_datalayer_variable`        | Single Data Layer Variable                                                                                        |
| `create_datalayer_variables_batch` | Multiple Data Layer Variables                                                                                     |
| `create_js_variable`               | Custom JavaScript variable (type `jsm`)                                                                           |
| `create_gtm_variable`              | Any variable type; `javascript=` shortcut for `jsm`                                                               |

### Modifying

| Tool                                      | Description                                                                                                                                                                                  |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `update_tag`                              | Partial in-place tag update (triggers, sequencing, firing option, consent, notes, paused, folder) — keeps tag ID |
| `update_gtm_variable`                     | Update a variable in place; `javascript=` shortcut for `jsm` |
| `set_tags_firing_option_batch`            | Bulk set `tagFiringOption` on multiple tags |
| `pause_tag` / `unpause_tag`               | Toggle a tag's `paused` flag (reversible) |
| `update_tag_consent_settings`             | Set consent config for one tag                                                                                                                                                               |
| `update_tags_consent_settings_batch`      | Set consent config for multiple tags                                                                                                                                                         |
| `update_tag_html`                         | Replace the HTML body of a Custom HTML tag                                                                                                                                                   |
| `update_tag_parameters`                   | Upsert raw GTM `parameter` dicts on any tag by `key` (works on every tag type — GA4 event/`gaawe`, config/`gtagjs`, conversion/`awct`, etc.)                                                 |
| `update_trigger_parameters`               | Overwrite top-level fields on a trigger in place (`name`, `filter`, `customEventFilter`, `autoEventFilter`, `interval`, `limit`, `checkValidation`, `waitForTags`) — keeps trigger ID stable |
| `update_trigger_filter`                   | Ergonomic wrapper to replace a trigger's filter list using `[{operator, lhs, rhs}, ...]`                                                                                                     |
| `add_firing_trigger_to_tags_batch`        | Append a firing trigger to multiple tags                                                                                                                                                     |
| `add_blocking_trigger_to_tags_batch`      | Append a blocking (exception) trigger to multiple tags                                                                                                                                       |
| `set_firing_triggers_on_tags_batch`       | Replace the firing-trigger list on multiple tags                                                                                                                                             |
| `remove_firing_trigger_from_tags_batch`   | Detach a specific firing trigger from multiple tags                                                                                                                                          |
| `remove_blocking_trigger_from_tags_batch` | Detach a specific blocking trigger from multiple tags                                                                                                                                        |

### Deleting

| Tool                  | Description                      |
| --------------------- | -------------------------------- |
| `delete_tag`          | Delete a tag from workspace      |
| `delete_gtm_variable` | Delete a variable from workspace |
| `delete_trigger`      | Delete a trigger from workspace  |

### Publishing

| Tool                    | Description                                  |
| ----------------------- | -------------------------------------------- |
| `publish_gtm_container` | Create version from workspace and publish it |

## Common Workflow Patterns

### 1. Discovery

```
list_gtm_accounts → list_gtm_containers(account_id) → list_gtm_workspaces(account_id, container_id)
```

### 2. Audit Tags

```
list_gtm_tags(account_id, container_id) → get_gtm_tag(account_id, container_id, tag_id)
```

### 3. Consent Audit & Update

```
list_gtm_tags → review consentSettings → update_tags_consent_settings_batch
```

### 4. Create & Publish

```
create_tag / create_trigger / create_datalayer_variable / create_js_variable → publish_gtm_container
```

### 5. Trigger Migration (swap firing trigger on existing tags)

```
create_trigger(new) → set_firing_triggers_on_tags_batch(tag_ids, [new_trigger_id])
    or
create_trigger(new) → add_firing_trigger_to_tags_batch(tag_ids, new_trigger_id)
                   → remove_firing_trigger_from_tags_batch(tag_ids, old_trigger_id)
                   → delete_trigger(old_trigger_id)
```

### 6. Consent-Aware Filtering (Exception / Guard Trigger)

```
create_js_variable(is_<cohort>_source) → create_trigger(customEvent + filters on variable)
    → add_blocking_trigger_to_tags_batch(tag_ids, trigger_id)   # exception
    or
    → set_firing_triggers_on_tags_batch(tag_ids, [trigger_id])  # replace firing
```

### 7. Version History / Change Audit ("what changed in version X?")

```
list_gtm_container_versions(account_id, container_id)
    → diff_gtm_container_versions(account_id, container_id, from_version_id=X-1, to_version_id=X)
    or
    → diff_gtm_container_versions(account_id, container_id, from_version_id=X)  # X → live
```

## GTM API v2 — Full Endpoint Reference

The GTM API v2 has 18 resource families with ~105 methods total. The table below shows implementation status.

### accounts

| Method            | Implemented | Tool                |
| ----------------- | ----------- | ------------------- |
| `accounts.list`   | Yes         | `list_gtm_accounts` |
| `accounts.get`    | No          | —                   |
| `accounts.update` | No          | —                   |

### accounts.containers

| Method                   | Implemented | Tool                                         |
| ------------------------ | ----------- | -------------------------------------------- |
| `containers.list`        | Yes         | `list_gtm_containers`, `test_gtm_connection` |
| `containers.get`         | No          | —                                            |
| `containers.create`      | No          | —                                            |
| `containers.update`      | No          | —                                            |
| `containers.delete`      | No          | —                                            |
| `containers.combine`     | No          | —                                            |
| `containers.lookup`      | No          | —                                            |
| `containers.move_tag_id` | No          | —                                            |
| `containers.snippet`     | No          | —                                            |

### accounts.containers.workspaces

| Method                        | Implemented | Tool                                    |
| ----------------------------- | ----------- | --------------------------------------- |
| `workspaces.list`             | Yes         | `list_gtm_workspaces`                   |
| `workspaces.get`              | No          | —                                       |
| `workspaces.create`           | No          | —                                       |
| `workspaces.update`           | No          | —                                       |
| `workspaces.delete`           | No          | —                                       |
| `workspaces.sync`             | No          | —                                       |
| `workspaces.resolve_conflict` | No          | —                                       |
| `workspaces.quick_preview`    | No          | —                                       |
| `workspaces.create_version`   | Yes         | `publish_gtm_container` (internal step) |
| `workspaces.getStatus`        | No          | —                                       |

### accounts.containers.workspaces.tags

| Method        | Implemented | Tool                                                                                                                                                                                                                                                                                      |
| ------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tags.list`   | Yes         | `list_gtm_tags`                                                                                                                                                                                                                                                                           |
| `tags.get`    | Yes         | `get_gtm_tag`                                                                                                                                                                                                                                                                             |
| `tags.create` | Yes         | `create_tag`                                                                                                                                                                                                                                                                              |
| `tags.update` | Yes         | Every tool under "Modifying" that touches tags |
| `tags.delete` | Yes         | `delete_tag`                                                                                                                                                                                                                                                                              |
| `tags.revert` | No          | —                                                                                                                                                                                                                                                                                         |

### accounts.containers.workspaces.triggers

| Method            | Implemented | Tool                                                 |
| ----------------- | ----------- | ---------------------------------------------------- |
| `triggers.list`   | Yes         | `list_gtm_triggers`                                  |
| `triggers.get`    | Yes         | (internal — used by `update_trigger_parameters`)     |
| `triggers.create` | Yes         | `create_trigger`                                     |
| `triggers.update` | Yes         | `update_trigger_parameters`, `update_trigger_filter` |
| `triggers.delete` | Yes         | `delete_trigger`                                     |
| `triggers.revert` | No          | —                                                    |

### accounts.containers.workspaces.variables

| Method             | Implemented | Tool                                                                                  |
| ------------------ | ----------- | ------------------------------------------------------------------------------------- |
| `variables.list`   | Yes         | `list_gtm_variables`                                                                  |
| `variables.get`    | Yes         | `get_gtm_variable` |
| `variables.create` | Yes         | `create_gtm_variable`, `create_js_variable`, `create_datalayer_variable(s_batch)` |
| `variables.update` | Yes         | `update_gtm_variable` |
| `variables.delete` | Yes         | `delete_gtm_variable`                                                                 |
| `variables.revert` | No          | —                                                                                     |

### accounts.containers.versions

| Method                | Implemented | Tool                                                                                               |
| --------------------- | ----------- | -------------------------------------------------------------------------------------------------- |
| `versions.publish`    | Yes         | `publish_gtm_container`                                                                            |
| `versions.list`       | No          | —                                                                                                  |
| `versions.get`        | Yes         | `get_gtm_container_version`, `diff_gtm_container_versions`                                         |
| `versions.update`     | No          | —                                                                                                  |
| `versions.delete`     | No          | —                                                                                                  |
| `versions.set_latest` | No          | —                                                                                                  |
| `versions.undelete`   | No          | —                                                                                                  |
| `versions.live`       | Yes         | `get_gtm_live_version`, `get_gtm_container_version` / `diff_gtm_container_versions` (via `"live"`) |

### accounts.containers.version_headers

| Method                   | Implemented | Tool                          |
| ------------------------ | ----------- | ----------------------------- |
| `version_headers.list`   | Yes         | `list_gtm_container_versions` |
| `version_headers.latest` | No          | —                             |

### accounts.containers.environments

| Method                     | Implemented | Tool |
| -------------------------- | ----------- | ---- |
| `environments.list`        | No          | —    |
| `environments.get`         | No          | —    |
| `environments.create`      | No          | —    |
| `environments.update`      | No          | —    |
| `environments.delete`      | No          | —    |
| `environments.reauthorize` | No          | —    |

### accounts.containers.workspaces.folders

| Method                            | Implemented | Tool |
| --------------------------------- | ----------- | ---- |
| `folders.list`                    | No          | —    |
| `folders.get`                     | No          | —    |
| `folders.create`                  | No          | —    |
| `folders.update`                  | No          | —    |
| `folders.delete`                  | No          | —    |
| `folders.entities`                | No          | —    |
| `folders.move_entities_to_folder` | No          | —    |
| `folders.revert`                  | No          | —    |

### accounts.containers.workspaces.built_in_variables

| Method                      | Implemented | Tool |
| --------------------------- | ----------- | ---- |
| `built_in_variables.list`   | No          | —    |
| `built_in_variables.create` | No          | —    |
| `built_in_variables.delete` | No          | —    |
| `built_in_variables.revert` | No          | —    |

### accounts.containers.workspaces.zones

| Method         | Implemented | Tool |
| -------------- | ----------- | ---- |
| `zones.list`   | No          | —    |
| `zones.get`    | No          | —    |
| `zones.create` | No          | —    |
| `zones.update` | No          | —    |
| `zones.delete` | No          | —    |
| `zones.revert` | No          | —    |

### accounts.containers.workspaces.templates

| Method             | Implemented | Tool |
| ------------------ | ----------- | ---- |
| `templates.list`   | No          | —    |
| `templates.get`    | No          | —    |
| `templates.create` | No          | —    |
| `templates.update` | No          | —    |
| `templates.delete` | No          | —    |
| `templates.revert` | No          | —    |

### accounts.containers.workspaces.transformations

| Method                   | Implemented | Tool |
| ------------------------ | ----------- | ---- |
| `transformations.list`   | No          | —    |
| `transformations.get`    | No          | —    |
| `transformations.create` | No          | —    |
| `transformations.update` | No          | —    |
| `transformations.delete` | No          | —    |
| `transformations.revert` | No          | —    |

### accounts.containers.workspaces.clients

| Method           | Implemented | Tool |
| ---------------- | ----------- | ---- |
| `clients.list`   | No          | —    |
| `clients.get`    | No          | —    |
| `clients.create` | No          | —    |
| `clients.update` | No          | —    |
| `clients.delete` | No          | —    |
| `clients.revert` | No          | —    |

### accounts.containers.workspaces.gtag_config

| Method               | Implemented | Tool |
| -------------------- | ----------- | ---- |
| `gtag_config.list`   | No          | —    |
| `gtag_config.get`    | No          | —    |
| `gtag_config.create` | No          | —    |
| `gtag_config.update` | No          | —    |
| `gtag_config.delete` | No          | —    |

### accounts.user_permissions

| Method                    | Implemented | Tool |
| ------------------------- | ----------- | ---- |
| `user_permissions.list`   | No          | —    |
| `user_permissions.get`    | No          | —    |
| `user_permissions.create` | No          | —    |
| `user_permissions.update` | No          | —    |
| `user_permissions.delete` | No          | —    |

## Priority for Future Implementation

### High — Complete CRUD on core resources

- `tags.revert`
- `triggers.revert`
- `workspaces.create`, `workspaces.get`

### Medium — Environments, versions, folders

- `environments.list`, `environments.create`
- `versions.list`
- `version_headers.latest`
- `folders.list`, `folders.create`, `folders.entities`
- `built_in_variables.list`, `built_in_variables.create`
- `workspaces.sync`, `workspaces.getStatus`

### Low — Advanced features

- `templates.*` (custom tag templates)
- `zones.*` (tag firing zones)
- `transformations.*` (server-side transformations)
- `clients.*` (server-side clients)
- `gtag_config.*` (gtag configurations)
- `user_permissions.*` (access management)
- `containers.snippet` (container snippet HTML)

## Testing

`uv run pytest` (tests live in `tests/`) and `uv run ruff check .`. Tests mock
the GTM client with `MagicMock` and patch `gtm_mcp.<module>.get_gtm_client` /
`_resolve_workspace_parent`, so no credentials or network are needed.
`tests/test_docs_tool_list.py` fails when the "Implemented Tools" section above
doesn't match the registered tools — update this file when adding/removing one.
