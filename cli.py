#!/usr/bin/env python3
"""
CLI for Google Tag Manager API via GTMClient.

Reads GOOGLE_APPLICATION_CREDENTIALS from the environment for service account auth.
Prints JSON to stdout, errors to stderr.

Usage:
    uv run python cli.py list-accounts
    uv run python cli.py list-containers --account_id 123456
    uv run python cli.py list-tags --account_id 123456 --container_id 7890123
    uv run python cli.py list-triggers --account_id 123456 --container_id 7890123
    uv run python cli.py list-variables --account_id 123456 --container_id 7890123
    uv run python cli.py list-workspaces --account_id 123456 --container_id 7890123
    uv run python cli.py get-tag --account_id 123456 --container_id 7890123 --tag_id 42
"""
import argparse
import json
import sys

from gtm_client_fixed import GTMClient


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _validate_cli_id(value, name):
    """Validate a GTM ID is a non-empty numeric string."""
    if not value or not str(value).strip().isdigit():
        print(json.dumps({"error": f"Invalid {name}: '{value}'. Must be a numeric string."}), file=sys.stderr)
        sys.exit(1)


def _workspace_parent(args):
    _validate_cli_id(args.account_id, "account_id")
    _validate_cli_id(args.container_id, "container_id")
    _validate_cli_id(args.workspace_id, "workspace_id")
    return f"accounts/{args.account_id}/containers/{args.container_id}/workspaces/{args.workspace_id}"


def _paginate(request_fn, result_key):
    """Fetch all pages from a paginated GTM API list endpoint."""
    items = []
    page_token = None
    while True:
        request = request_fn(pageToken=page_token) if page_token else request_fn()
        result = request.execute()
        items.extend(result.get(result_key, []))
        page_token = result.get('nextPageToken')
        if not page_token:
            break
    return items


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def list_accounts(client, _args):
    items = _paginate(
        lambda **kw: client.service.accounts().list(**kw),
        'account',
    )
    print(json.dumps(items, indent=2))


def list_containers(client, args):
    _validate_cli_id(args.account_id, "account_id")
    parent = f"accounts/{args.account_id}"
    items = _paginate(
        lambda **kw: client.service.accounts().containers().list(parent=parent, **kw),
        'container',
    )
    print(json.dumps(items, indent=2))


def list_tags(client, args):
    parent = _workspace_parent(args)
    items = _paginate(
        lambda **kw: client.service.accounts().containers().workspaces().tags().list(parent=parent, **kw),
        'tag',
    )
    print(json.dumps(items, indent=2))


def list_triggers(client, args):
    parent = _workspace_parent(args)
    items = _paginate(
        lambda **kw: client.service.accounts().containers().workspaces().triggers().list(parent=parent, **kw),
        'trigger',
    )
    print(json.dumps(items, indent=2))


def list_variables(client, args):
    parent = _workspace_parent(args)
    items = _paginate(
        lambda **kw: client.service.accounts().containers().workspaces().variables().list(parent=parent, **kw),
        'variable',
    )
    print(json.dumps(items, indent=2))


def list_workspaces(client, args):
    _validate_cli_id(args.account_id, "account_id")
    _validate_cli_id(args.container_id, "container_id")
    parent = f"accounts/{args.account_id}/containers/{args.container_id}"
    items = _paginate(
        lambda **kw: client.service.accounts().containers().workspaces().list(parent=parent, **kw),
        'workspace',
    )
    print(json.dumps(items, indent=2))


def get_tag(client, args):
    _validate_cli_id(args.tag_id, "tag_id")
    path = f"{_workspace_parent(args)}/tags/{args.tag_id}"
    tag = client.service.accounts().containers().workspaces().tags().get(
        path=path
    ).execute()
    print(json.dumps(tag, indent=2))


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="GTM CLI -- query Google Tag Manager via service account")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared argument groups (used via parents= to avoid repetition)
    account_parser = argparse.ArgumentParser(add_help=False)
    account_parser.add_argument("--account_id", required=True)

    container_parser = argparse.ArgumentParser(add_help=False)
    container_parser.add_argument("--container_id", required=True)

    workspace_parser = argparse.ArgumentParser(add_help=False)
    workspace_parser.add_argument("--workspace_id", default="1")

    # list-accounts (no extra args)
    subparsers.add_parser("list-accounts", help="List all GTM accounts")

    # list-containers (account only)
    subparsers.add_parser(
        "list-containers", help="List containers in an account",
        parents=[account_parser],
    )

    # Workspace-level listing commands share account + container + workspace args
    for name, help_text in [
        ("list-tags", "List tags in a workspace"),
        ("list-triggers", "List triggers in a workspace"),
        ("list-variables", "List variables in a workspace"),
    ]:
        subparsers.add_parser(
            name, help=help_text,
            parents=[account_parser, container_parser, workspace_parser],
        )

    # list-workspaces (account + container, no workspace_id)
    subparsers.add_parser(
        "list-workspaces", help="List workspaces in a container",
        parents=[account_parser, container_parser],
    )

    # get-tag (account + container + workspace + tag_id)
    p = subparsers.add_parser(
        "get-tag", help="Get full details of a tag",
        parents=[account_parser, container_parser, workspace_parser],
    )
    p.add_argument("--tag_id", required=True)

    args = parser.parse_args()

    commands = {
        "list-accounts": list_accounts,
        "list-containers": list_containers,
        "list-tags": list_tags,
        "list-triggers": list_triggers,
        "list-variables": list_variables,
        "list-workspaces": list_workspaces,
        "get-tag": get_tag,
    }

    try:
        client = GTMClient()
        commands[args.command](client, args)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
