#!/bin/sh
# Container entrypoint — materializes the GCP service account JSON to disk
# (the Google client expects a file path via GOOGLE_APPLICATION_CREDENTIALS),
# then launches the MCP server over the transport configured via env vars.
set -e

if [ -n "$GCP_SA_JSON" ]; then
  printf '%s' "$GCP_SA_JSON" > /tmp/gcp-sa.json
  chmod 600 /tmp/gcp-sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-sa.json
fi

# Defaults for hosted deployments. Local stdio users never reach here.
: "${MCP_TRANSPORT:=streamable-http}"
: "${HOST:=0.0.0.0}"
: "${PORT:=8000}"
export MCP_TRANSPORT HOST PORT

exec python /app/fastmcp_gtm_server.py
