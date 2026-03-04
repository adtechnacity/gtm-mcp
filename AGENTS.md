# AGENTS.md — AI Agent Reference for GTM MCP Server

## Architecture

Three core Python files:

| File | Role |
|------|------|
| `fastmcp_gtm_server.py` | MCP server — 21 `@mcp.tool()` functions exposed to AI agents |
| `gtm_client_fixed.py` | GTM API client — OAuth2 auth, token refresh, wraps `google-api-python-client` |
| `gtm_components.py` | Local template builders — no API calls, produce JSON dicts for tags/triggers/variables |

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

Most tools require `account_id` + `container_id`. Some also need `workspace_id` (defaults to `"1"`).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GTM_CREDENTIALS_FILE` | `credentials.json` | Path to Google OAuth2 client secrets JSON |
| `GTM_TOKEN_FILE` | `token.json` | Path to stored OAuth2 token (auto-created on first auth) |

## Auth Flow

1. On first use, `GTMClient` looks for an existing token file
2. If valid and has required scopes (`tagmanager.edit.containers`, `tagmanager.publish`), uses it
3. If expired, attempts refresh
4. If no valid token, launches browser-based OAuth2 flow
5. Token is saved for subsequent runs

## Implemented Tools (21)

### Discovery

| Tool | Description |
|------|-------------|
| `test_gtm_connection` | Verify OAuth2 credentials work by listing containers |
| `list_gtm_accounts` | List all accessible GTM accounts |
| `list_gtm_containers` | List containers in an account |
| `list_gtm_workspaces` | List workspaces in a container |

### Reading

| Tool | Description |
|------|-------------|
| `list_gtm_tags` | List all tags with consent settings |
| `list_gtm_triggers` | List all triggers with filters |
| `list_gtm_variables` | List all variables |
| `get_gtm_tag` | Get full tag details by ID |

### Creating

| Tool | Description |
|------|-------------|
| `create_ga4_setup` | Full GA4 setup (config tag + events + triggers + variables) |
| `create_facebook_pixel_setup` | Facebook Pixel base tag + triggers |
| `create_complete_ecommerce_setup` | GA4 + FB Pixel + conversion tracking + form/click tracking |
| `create_datalayer_variable` | Single Data Layer Variable |
| `create_datalayer_variables_batch` | Multiple Data Layer Variables |
| `create_trigger` | Custom event trigger |

### Modifying

| Tool | Description |
|------|-------------|
| `update_tag_consent_settings` | Set consent config for one tag |
| `update_tags_consent_settings_batch` | Set consent config for multiple tags |
| `add_firing_trigger_to_tags_batch` | Add a trigger to multiple tags |

### Deleting

| Tool | Description |
|------|-------------|
| `delete_gtm_variable` | Delete a variable from workspace |

### Publishing

| Tool | Description |
|------|-------------|
| `publish_gtm_container` | Create version from workspace and publish it |

### Templates (Local Only)

| Tool | Description |
|------|-------------|
| `generate_ga4_template` | Generate GA4 tag JSON without API calls |

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
create_ga4_setup / create_trigger / create_datalayer_variable → publish_gtm_container
```

### 5. Full Ecommerce Setup
```
test_gtm_connection → create_complete_ecommerce_setup → publish_gtm_container
```

## GTM API v2 — Full Endpoint Reference

The GTM API v2 has 18 resource families with ~105 methods total. This server currently implements 14 unique API methods. The table below shows implementation status.

### accounts

| Method | Implemented | Tool |
|--------|-------------|------|
| `accounts.list` | Yes | `list_gtm_accounts` |
| `accounts.get` | No | — |
| `accounts.update` | No | — |

### accounts.containers

| Method | Implemented | Tool |
|--------|-------------|------|
| `containers.list` | Yes | `list_gtm_containers`, `test_gtm_connection` |
| `containers.get` | Yes | (in `gtm_client_fixed.py` only) |
| `containers.create` | No | — |
| `containers.update` | No | — |
| `containers.delete` | No | — |
| `containers.combine` | No | — |
| `containers.lookup` | No | — |
| `containers.move_tag_id` | No | — |
| `containers.snippet` | No | — |

### accounts.containers.workspaces

| Method | Implemented | Tool |
|--------|-------------|------|
| `workspaces.list` | Yes | `list_gtm_workspaces` |
| `workspaces.get` | No | — |
| `workspaces.create` | No | — |
| `workspaces.update` | No | — |
| `workspaces.delete` | No | — |
| `workspaces.sync` | No | — |
| `workspaces.resolve_conflict` | No | — |
| `workspaces.quick_preview` | No | — |
| `workspaces.create_version` | Yes | `publish_gtm_container` (internal step) |
| `workspaces.getStatus` | No | — |

### accounts.containers.workspaces.tags

| Method | Implemented | Tool |
|--------|-------------|------|
| `tags.list` | Yes | `list_gtm_tags` |
| `tags.get` | Yes | `get_gtm_tag` |
| `tags.create` | Yes | `create_ga4_setup`, `create_facebook_pixel_setup`, `create_complete_ecommerce_setup` |
| `tags.update` | Yes | `update_tag_consent_settings`, `update_tags_consent_settings_batch`, `add_firing_trigger_to_tags_batch` |
| `tags.delete` | No | — |
| `tags.revert` | No | — |

### accounts.containers.workspaces.triggers

| Method | Implemented | Tool |
|--------|-------------|------|
| `triggers.list` | Yes | `list_gtm_triggers` |
| `triggers.get` | No | — |
| `triggers.create` | Yes | `create_trigger`, `create_ga4_setup`, `create_facebook_pixel_setup`, `create_complete_ecommerce_setup` |
| `triggers.update` | No | — |
| `triggers.delete` | No | — |
| `triggers.revert` | No | — |

### accounts.containers.workspaces.variables

| Method | Implemented | Tool |
|--------|-------------|------|
| `variables.list` | Yes | `list_gtm_variables` |
| `variables.get` | No | — |
| `variables.create` | Yes | `create_datalayer_variable`, `create_datalayer_variables_batch`, `create_ga4_setup`, `create_complete_ecommerce_setup` |
| `variables.update` | No | — |
| `variables.delete` | Yes | `delete_gtm_variable` |
| `variables.revert` | No | — |

### accounts.containers.versions

| Method | Implemented | Tool |
|--------|-------------|------|
| `versions.publish` | Yes | `publish_gtm_container` |
| `versions.list` | No | — |
| `versions.get` | No | — |
| `versions.update` | No | — |
| `versions.delete` | No | — |
| `versions.set_latest` | No | — |
| `versions.undelete` | No | — |
| `versions.live` | No | — |

### accounts.containers.version_headers

| Method | Implemented | Tool |
|--------|-------------|------|
| `version_headers.list` | No | — |
| `version_headers.latest` | No | — |

### accounts.containers.environments

| Method | Implemented | Tool |
|--------|-------------|------|
| `environments.list` | No | — |
| `environments.get` | No | — |
| `environments.create` | No | — |
| `environments.update` | No | — |
| `environments.delete` | No | — |
| `environments.reauthorize` | No | — |

### accounts.containers.workspaces.folders

| Method | Implemented | Tool |
|--------|-------------|------|
| `folders.list` | No | — |
| `folders.get` | No | — |
| `folders.create` | No | — |
| `folders.update` | No | — |
| `folders.delete` | No | — |
| `folders.entities` | No | — |
| `folders.move_entities_to_folder` | No | — |
| `folders.revert` | No | — |

### accounts.containers.workspaces.built_in_variables

| Method | Implemented | Tool |
|--------|-------------|------|
| `built_in_variables.list` | No | — |
| `built_in_variables.create` | No | — |
| `built_in_variables.delete` | No | — |
| `built_in_variables.revert` | No | — |

### accounts.containers.workspaces.zones

| Method | Implemented | Tool |
|--------|-------------|------|
| `zones.list` | No | — |
| `zones.get` | No | — |
| `zones.create` | No | — |
| `zones.update` | No | — |
| `zones.delete` | No | — |
| `zones.revert` | No | — |

### accounts.containers.workspaces.templates

| Method | Implemented | Tool |
|--------|-------------|------|
| `templates.list` | No | — |
| `templates.get` | No | — |
| `templates.create` | No | — |
| `templates.update` | No | — |
| `templates.delete` | No | — |
| `templates.revert` | No | — |

### accounts.containers.workspaces.transformations

| Method | Implemented | Tool |
|--------|-------------|------|
| `transformations.list` | No | — |
| `transformations.get` | No | — |
| `transformations.create` | No | — |
| `transformations.update` | No | — |
| `transformations.delete` | No | — |
| `transformations.revert` | No | — |

### accounts.containers.workspaces.clients

| Method | Implemented | Tool |
|--------|-------------|------|
| `clients.list` | No | — |
| `clients.get` | No | — |
| `clients.create` | No | — |
| `clients.update` | No | — |
| `clients.delete` | No | — |
| `clients.revert` | No | — |

### accounts.containers.workspaces.gtag_config

| Method | Implemented | Tool |
|--------|-------------|------|
| `gtag_config.list` | No | — |
| `gtag_config.get` | No | — |
| `gtag_config.create` | No | — |
| `gtag_config.update` | No | — |
| `gtag_config.delete` | No | — |

### accounts.user_permissions

| Method | Implemented | Tool |
|--------|-------------|------|
| `user_permissions.list` | No | — |
| `user_permissions.get` | No | — |
| `user_permissions.create` | No | — |
| `user_permissions.update` | No | — |
| `user_permissions.delete` | No | — |

## Priority for Future Implementation

### High — Complete CRUD on core resources
- `tags.delete`, `tags.revert`
- `triggers.get`, `triggers.update`, `triggers.delete`
- `variables.get`, `variables.update`
- `workspaces.create`, `workspaces.get`

### Medium — Environments, versions, folders
- `environments.list`, `environments.create`
- `versions.list`, `versions.get`, `versions.live`
- `version_headers.list`, `version_headers.latest`
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

All old test files have been removed. Tests need to be written using pytest + pytest-asyncio.
