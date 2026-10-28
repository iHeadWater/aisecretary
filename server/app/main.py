from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.app.api import router as api_router
from server.app.database import init_db
from server.app.mcp_server import mcp

# Transport params moved off the MCPServer constructor in mcp 2.x.
# host="0.0.0.0" disables DNS-rebinding auto-allowlist so Docker hostname
# "aisecretary" is accepted. streamable_http_path="/" keeps the endpoint at
# /mcp when this app is mounted there (not /mcp/mcp).
mcp_app = mcp.streamable_http_app(host="0.0.0.0", streamable_http_path="/")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize the database and run the MCP session manager."""
    init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="aisecretary",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow local and Docker-network callers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://host.docker.internal:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routes (for CLI and direct HTTP access)
app.include_router(api_router)

# MCP Streamable HTTP transport — same URL for GET (SSE) and POST (JSON-RPC)
app.mount("/mcp", mcp_app)


@app.get("/health")
def health():
    return {"status": "ok"}
