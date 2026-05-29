"""Health check route."""
from fastapi import APIRouter

from src.api.schemas.api_models import HealthResponse, ServerHealthInfo
from src.mcp_clients.connections import get_mcp

router = APIRouter(tags=["health"])


def _aggregate_status(server_healths: list[ServerHealthInfo]) -> str:
    """Roll up per-server status into an overall service status.

    Used by orchestrators (Kubernetes/Render) to decide if this instance
    should receive traffic.
    """
    if any(s.status == "unhealthy" for s in server_healths):
        return "unhealthy"
    if any(s.status == "degraded" for s in server_healths):
        return "degraded"
    return "ok"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + dependency-health check.

    Returns per-MCP-server health state from the background monitor.
    Production orchestrators (Kubernetes, Render) can poll this and route
    traffic accordingly.
    """
    mcp = get_mcp()
    if mcp is None:
        return HealthResponse(
            status="ok",
            version="0.1.0",
            workflow_loaded=True,
            mcp_servers_connected=[],
            mcp_servers=[],
        )

    connected_names: list[str] = []
    try:
        connected_names = list(mcp._clients.keys())  # type: ignore[attr-defined]
    except Exception:
        connected_names = ["(unknown)"]

    server_healths: list[ServerHealthInfo] = []
    try:
        for snap in mcp.health_snapshot():
            server_healths.append(ServerHealthInfo(**snap))
    except Exception:
        # Health monitor not yet running (e.g., during shutdown).
        pass

    return HealthResponse(
        status=_aggregate_status(server_healths),
        version="0.1.0",
        workflow_loaded=True,
        mcp_servers_connected=connected_names,
        mcp_servers=server_healths,
    )