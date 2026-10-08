"""AGENTS.md must list exactly the registered tools, so the docs can't drift."""
import asyncio
import re
from pathlib import Path

from gtm_mcp.server import mcp

_TOOL_VERBS = ("create", "update", "delete", "list", "get", "set", "add", "remove",
               "pause", "unpause", "publish", "diff", "generate", "test")
TOOL_REF = re.compile(rf"``((?:{'|'.join(_TOOL_VERBS)})_\w+)``")

AGENTS_MD = Path(__file__).resolve().parent.parent / "AGENTS.md"


def test_agents_md_lists_every_registered_tool():
    registered = {t.name for t in asyncio.run(mcp.list_tools())}
    tools_section = AGENTS_MD.read_text().split("## Implemented Tools", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `(\w+)`", tools_section, flags=re.M))
    documented |= set(re.findall(r"^\| `\w+` / `(\w+)`", tools_section, flags=re.M))
    assert documented == registered, {
        "undocumented": sorted(registered - documented),
        "stale_in_docs": sorted(documented - registered),
    }


def test_tool_descriptions_only_reference_registered_tools():
    tools = asyncio.run(mcp.list_tools())
    registered = {t.name for t in tools}
    stale = {
        (t.name, ref)
        for t in tools
        for ref in TOOL_REF.findall(t.description or "")
        if ref not in registered
    }
    assert not stale, sorted(stale)
