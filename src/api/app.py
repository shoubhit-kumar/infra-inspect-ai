"""FastAPI application with MCP lifecycle management.

The MCP servers and Langfuse trace are heavy to construct, so we bring them
up once on app startup and tear them down on shutdown - same pattern as
test_workflow.py but at process scope instead of per-call.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import health, inspections, memory
from src.config.settings import get_settings
from src.mcp_clients.connections import set_mcp_manager
from src.mcp_clients.manager import MCPConnectionManager
from src.utils.cache import enable_dev_cache
from src.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: boot MCP servers. Shutdown: tear them down."""
    configure_logging()
    enable_dev_cache()

    settings = get_settings()
    mcp_servers: dict[str, list[str]] = {}
    if settings.mcp_enabled:
        mcp_servers = {
            "filesystem":   settings.mcp_filesystem_command,
            "workorder":    settings.mcp_workorder_command,
            "notification": settings.mcp_notification_command,
        }

    manager = MCPConnectionManager(mcp_servers)
    try:
        manager.__enter__()
        set_mcp_manager(manager if mcp_servers else None)
        logger.info("api.startup.complete", mcp_servers=list(mcp_servers.keys()))
        yield
    finally:
        logger.info("api.shutdown.starting")
        set_mcp_manager(None)
        try:
            manager.__exit__(None, None, None)
        except Exception as e:
            logger.warning("api.shutdown.mcp_teardown_warning", error=str(e))
        logger.info("api.shutdown.complete")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="infra-inspect-ai",
        version="0.1.0",
        description=(
            "AI-powered building inspection and compliance automation. "
            "Submit photos and inspector notes, receive grounded violations, "
            "risk assessment, work orders, and follow-up plan."
        ),
        lifespan=lifespan,
    )

    # CORS - permissive for local dev; tighten in production deployment
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(inspections.router)
    app.include_router(memory.router)

    return app


app = create_app()