# Starts the MCP server (stdio transport) for an MCP-aware client.
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe apps\mcp\server.py
