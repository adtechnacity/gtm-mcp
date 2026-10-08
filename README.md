# Google Tag Manager MCP Server

An MCP server that exposes Google Tag Manager API v2 as tools for AI agents like Claude. Manage tags, triggers, variables, consent settings, and publishing through natural language.

## Features

- **MCP tools** covering discovery, CRUD, version history, consent management, batch operations, and publishing
- **Service account or OAuth authentication** — service account is headless and works in containers
- **Batch operations** for bulk consent updates and variable creation
- **CLI tool** for direct GTM API queries from the command line

## Setup

### 1. Install Dependencies

```bash
uv sync
```

### 2. Create a Service Account

#### Option A: Using gcloud CLI

```bash
# Create the service account
gcloud iam service-accounts create gtm-mcp \
  --project=YOUR_PROJECT_ID \
  --display-name="GTM MCP Server" \
  --description="Service account for GTM MCP server"

# Download the key
gcloud iam service-accounts keys create /path/to/sa-key.json \
  --iam-account=gtm-mcp@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Then enable the Tag Manager API:

```bash
gcloud services enable tagmanager.googleapis.com --project=YOUR_PROJECT_ID
```

#### Option B: Using Google Cloud Console

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Tag Manager API** under "APIs & Services" > "Library"
4. Go to "APIs & Services" > "Credentials"
5. Click "Create Credentials" > "Service Account"
6. Grant appropriate roles and click "Done"
7. Click on the service account, go to "Keys" > "Add Key" > "Create new key" > JSON
8. Save the JSON key file

#### Grant GTM Access

Add the service account email (e.g. `gtm-mcp@YOUR_PROJECT_ID.iam.gserviceaccount.com`) as a user in GTM:

- Go to GTM > Admin > Account > User Management
- Add the service account email with **Edit** and **Publish** permissions

Set the env var:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
```

### 3. Configure Your MCP Client

Add the server to your MCP client config (Claude Desktop, Claude Code, etc.):

```json
{
  "mcpServers": {
    "gtm": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/gtm-mcp", "mcp-gtm-server"],
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account-key.json"
      }
    }
  }
}
```

Or using the installed entry point:

```json
{
  "mcpServers": {
    "gtm": {
      "command": "mcp-gtm-server",
      "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account-key.json"
      }
    }
  }
}
```

## Tools

The full, always-current tool list (checked by `tests/test_docs_tool_list.py`)
is in [AGENTS.md](AGENTS.md#implemented-tools). Recipes for the less obvious ones:

### Updating tag parameters

`update_tag_parameters` is the generic edit path for any tag's `parameter` array. Each item must be a complete GTM parameter dict — same shape `get_gtm_tag` returns. Items are upserted by their `key` field; everything else on the tag is left alone.

**Add or change `eventParameters` on a GA4 event tag (`gaawe`) without recreating it:**

1. Read the tag with `get_gtm_tag` to see the current `eventParameters` (a `list`-typed parameter whose `list` is a sequence of `map` items, each with inner `name`/`value` keys).
2. Build the merged list locally (append a new map for each new parameter, replace inner maps to overwrite).
3. Call `update_tag_parameters` with one entry whose `key` is `eventParameters` and whose `list` is the merged sequence:

```json
{
  "key": "eventParameters",
  "type": "list",
  "list": [
    {
      "type": "map",
      "map": [
        { "key": "name", "type": "template", "value": "item_id" },
        { "key": "value", "type": "template", "value": "{{DLV - item_id}}" }
      ]
    },
    {
      "type": "map",
      "map": [
        { "key": "name", "type": "template", "value": "currency" },
        { "key": "value", "type": "template", "value": "USD" }
      ]
    }
  ]
}
```

The whole `eventParameters` list is replaced atomically — read-then-merge locally rather than calling the tool twice. Other top-level params (`eventName`, `measurementIdOverride`, `userProperties`, etc.) are untouched.

### Updating trigger filters

`update_trigger_parameters` rewrites top-level fields on a trigger without changing the trigger ID. The most common use is widening or narrowing a trigger's `filter` conditions as a route/URL pattern evolves — useful because the alternative (delete + recreate) yields a new trigger ID that breaks every consuming tag's `firingTriggerId` list.

**Widen "Add to Cart Navigate" from `Page Path contains /create` to a regex matching `/create` or `/studio`:**

```python
update_trigger_parameters(
    account_id="6332661990",
    container_id="239933263",
    workspace_id="136",
    trigger_id="7",
    fields={
        "filter": [{
            "type": "matchRegex",
            "parameter": [
                {"type": "template", "key": "arg0", "value": "{{Page Path}}"},
                {"type": "template", "key": "arg1", "value": "/(create|studio)(?:[?/]|$)"},
            ],
        }],
    },
)
```

Or with the ergonomic wrapper:

```python
update_trigger_filter(
    account_id="6332661990",
    container_id="239933263",
    workspace_id="136",
    trigger_id="7",
    conditions=[
        {"operator": "matchRegex", "lhs": "{{Page Path}}", "rhs": "/(create|studio)(?:[?/]|$)"},
    ],
)
```

List-valued fields (`filter`, `customEventFilter`, `autoEventFilter`) replace wholesale — pass `[]` to clear. Pass `None` for any _optional_ key to remove it from the trigger; `name` is required by GTM and rejects `None` (omit the key to leave it unchanged). Keys not in `fields` are preserved. A missing trigger surfaces as a clear 404; a fingerprint mismatch surfaces as a 409 mentioning the workspace and trigger ID.

## CLI Tool

Query GTM directly from the command line (uses the same service account credentials):

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

uv run gtm-cli list-accounts
uv run gtm-cli list-containers --account_id 123456
uv run gtm-cli list-tags --account_id 123456 --container_id 7890123
uv run gtm-cli list-triggers --account_id 123456 --container_id 7890123
uv run gtm-cli list-variables --account_id 123456 --container_id 7890123
uv run gtm-cli list-workspaces --account_id 123456 --container_id 7890123
uv run gtm-cli get-tag --account_id 123456 --container_id 7890123 --tag_id 42
```

## Usage Examples

```
# Discover your GTM setup
List my GTM accounts, then show containers for account 123456

# Create a GA4 config tag
Create a gtagjs tag with measurement ID G-XXXXXXXXXX in account 123456, container 7890123

# Audit consent settings
List all tags in my container and show which ones are missing consent configuration

# Bulk update consent
Set ad_storage and analytics_storage consent requirements on tags 1, 2, 3, 4, 5

# Create a Custom HTML tag
Create a custom HTML tag that loads my tracking script, firing on all pages
```

## Running the Server

```bash
# Using the convenience script
./run_server.sh

# Or directly
uv run mcp-gtm-server

# HTTP (hosted) instead of stdio
MCP_TRANSPORT=streamable-http PORT=8000 uv run mcp-gtm-server
```

## File Structure

```
gtm-mcp/
├── src/gtm_mcp/
│   ├── server.py        # Entry point (`mcp-gtm-server`): registers tools, picks transport
│   ├── read_tools.py    # Discovery, read and version-history tools
│   ├── write_tools.py   # Create/update/delete/publish tools
│   ├── helpers.py       # Shared `mcp` instance, GTM client, validation, batch + diff helpers
│   ├── client.py        # Auth (service account / OAuth) and the googleapiclient service
│   └── cli.py           # `gtm-cli`: read-only subcommands, JSON to stdout
├── tests/               # pytest, mocked GTM client (no credentials needed)
├── docs/runbooks/       # As-built notes for specific containers
├── fastmcp_gtm_server.py  # Back-compat launcher for existing MCP configs
├── Dockerfile, entrypoint.sh, buildspec.yml  # Hosted (CodeBuild → ECR) image
└── AGENTS.md            # AI agent reference & GTM API coverage
```

## Authentication

Two options, checked in this order:

1. **Service account** — set `GOOGLE_APPLICATION_CREDENTIALS` to the JSON key path. The service account must be a GTM user with Edit + Publish. Headless; this is what the hosted image uses (`GCP_SA_JSON` is written to disk by `entrypoint.sh`).
2. **OAuth desktop flow** — set `GOOGLE_OAUTH_CLIENT_SECRET` to a Desktop App client secret JSON. Opens a browser once and caches the token in `~/.gtm-mcp/token.json`.

## AI Agent Reference

See [AGENTS.md](AGENTS.md) for:

- Full GTM API v2 endpoint reference (105 methods across 18 resource families)
- Implementation status of each endpoint
- Common workflow patterns
- Priority list for future implementation

## License

MIT — see [LICENSE](LICENSE)
