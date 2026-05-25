"""Health check route."""
from fastapi import APIRouter

from src.api.schemas.api_models import HealthResponse
from src.mcp_clients.connections import get_mcp

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check. Reports MCP server connection state."""
    mcp = get_mcp()
    if mcp is None:
        servers: list[str] = []
    else:
        # MCPConnectionManager has a private _clients dict; we expose names only.
        try:
            servers = list(mcp._clients.keys())  # type: ignore[attr-defined]
        except Exception:
            servers = ["(unknown)"]

    return HealthResponse(
        status="ok",
        version="0.1.0",
        workflow_loaded=True,
        mcp_servers_connected=servers,
    )