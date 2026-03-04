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

def _workspace_parent(args):
    return f"accounts/{args.account_id}/containers/{args.container_id}/workspaces/{args.workspace_id}"


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def list_accounts(client, _args):
    result = client.service.accounts().list().execute()
    print(json.dumps(result.get('account', []), indent=2))


def list_containers(client, args):
    parent = f"accounts/{args.account_id}"
    result = client.service.accounts().containers().list(parent=parent).execute()
    print(json.dumps(result.get('container', []), indent=2))


def list_tags(client, args):
    parent = _workspace_parent(args)
    result = client.service.accounts().containers().workspaces().tags().list(
        parent=parent
    ).execute()
    print(json.dumps(result.get('tag', []), indent=2))


def list_triggers(client, args):
    parent = _workspace_parent(args)
    result = client.service.accounts().containers().workspaces().triggers().list(
        parent=parent
    ).execute()
    print(json.dumps(result.get('trigger', []), indent=2))


def list_variables(client, args):
    parent = _workspace_parent(args)
    result = client.service.accounts().containers().workspaces().variables().list(
        parent=parent
    ).execute()
    print(json.dumps(result.get('variable', []), indent=2))


def list_workspaces(client, args):
    parent = f"accounts/{args.account_id}/containers/{args.container_id}"
    result = client.service.accounts().containers().workspaces().list(
        parent=parent
    ).execute()
    print(json.dumps(result.get('workspace', []), indent=2))


def get_tag(client, args):
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
