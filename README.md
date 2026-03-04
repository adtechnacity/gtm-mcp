# Google Tag Manager MCP Server

An MCP server that exposes Google Tag Manager API v2 as tools for AI agents like Claude. Manage tags, triggers, variables, consent settings, and publishing through natural language.

## Features

- **18 MCP tools** covering discovery, CRUD, consent management, batch operations, and publishing
- **Service account authentication** — headless, no browser flow, works in containers
- **Template builder** for generating GTM component JSON locally
- **Batch operations** for bulk consent updates and variable creation
- **CLI tool** for direct GTM API queries from the command line

## Setup

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
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
      "args": ["run", "python", "/path/to/gtm-mcp/fastmcp_gtm_server.py"],
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

## Available Tools (18)

### Discovery
- `test_gtm_connection` — Verify service account credentials
- `list_gtm_accounts` — List all accessible GTM accounts
- `list_gtm_containers` — List containers in an account
- `list_gtm_workspaces` — List workspaces in a container

### Reading
- `list_gtm_tags` — List all tags with consent settings
- `list_gtm_triggers` — List all triggers with filters
- `list_gtm_variables` — List all variables
- `get_gtm_tag` — Get full tag details by ID

### Creating
- `create_tag` — Create any tag type (GA4, Custom HTML, Facebook Pixel, Google Ads, etc.)
- `create_trigger` — Create a custom event trigger
- `create_datalayer_variable` — Create a single Data Layer Variable
- `create_datalayer_variables_batch` — Create multiple Data Layer Variables

### Modifying
- `update_tag_consent_settings` — Set consent config for one tag
- `update_tags_consent_settings_batch` — Set consent config for multiple tags
- `add_firing_trigger_to_tags_batch` — Add a trigger to multiple tags

### Deleting
- `delete_gtm_variable` — Delete a variable from workspace

### Publishing
- `publish_gtm_container` — Create version from workspace and publish

### Templates (Local Only)
- `generate_ga4_template` — Generate GA4 tag JSON without API calls

## CLI Tool

Query GTM directly from the command line (uses the same service account credentials):

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

uv run python cli.py list-accounts
uv run python cli.py list-containers --account_id 123456
uv run python cli.py list-tags --account_id 123456 --container_id 7890123
uv run python cli.py list-triggers --account_id 123456 --container_id 7890123
uv run python cli.py list-variables --account_id 123456 --container_id 7890123
uv run python cli.py list-workspaces --account_id 123456 --container_id 7890123
uv run python cli.py get-tag --account_id 123456 --container_id 7890123 --tag_id 42
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

# Or manually with uv
uv run python fastmcp_gtm_server.py
```

## File Structure

```
gtm-mcp/
├── fastmcp_gtm_server.py      # MCP server entry point — 10 read/query tools + main()
├── fastmcp_gtm_write_tools.py # 8 write tools (imported by server)
├── fastmcp_gtm_helpers.py     # Shared mcp instance, GTM client, internal helpers
├── gtm_client_fixed.py        # GTM API client with service account auth
├── gtm_components.py          # Template builder (no API calls)
├── cli.py                     # CLI tool (7 read-only subcommands)
├── pyproject.toml             # Project config & dependencies
├── requirements.txt           # pip dependencies
├── run_server.sh              # Launch script
├── AGENTS.md                  # AI agent reference & full API coverage
├── LICENSE                    # MIT
└── README.md                  # This file
```

## Authentication

Uses Google Service Account credentials. Set `GOOGLE_APPLICATION_CREDENTIALS` to the path of your service account JSON key file. The service account must be added as a user in GTM with appropriate permissions (Edit + Publish). No browser flow, no token files — works headless in containers.

## AI Agent Reference

See [AGENTS.md](AGENTS.md) for:
- Full GTM API v2 endpoint reference (105 methods across 18 resource families)
- Implementation status of each endpoint
- Common workflow patterns
- Priority list for future implementation

## License

MIT — see [LICENSE](LICENSE)
