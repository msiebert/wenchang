# ruff: noqa: F821
# pyright: basic, reportUndefinedVariable=false
from mcp.server.mcpserver import MCPServer

from wenchang.mcp import memory_instructions, register_memory_tools

# slots, client, resolver, policy, and credentials_from_context as in the setup page.
prompt = memory_instructions(slots) + (
    "\n## Tone\n\nWhen you save something, say so in one short sentence.\n"
)
server = MCPServer("inkwell-memory", instructions=prompt)
register_memory_tools(
    server,
    prompt=prompt,  # the same text as the instructions
    client=client,
    resolver=resolver,
    policy=policy,
    credentials_from_context=credentials_from_context,
    source="inkwell-web",
)
