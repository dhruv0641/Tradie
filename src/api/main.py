"""FastAPI application factory and middleware configuration for AI Trader Dashboard."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router as api_router
from src.api.state import TradingSystemState
from src.config.models import AppConfig

logger = structlog.get_logger("api.main")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifecycle management context."""
    logger.info("Starting AI Trader Dashboard Control API backend")
    yield
    logger.info("Shutting down AI Trader Dashboard Control API backend")


def create_app(
    config: AppConfig | None = None,
    system_state: TradingSystemState | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Args:
        config: Optional full AppConfig instance.
        system_state: Optional pre-configured TradingSystemState instance.

    Returns:
        FastAPI: Configured application instance.
    """
    app_config = config or AppConfig()
    app_state = system_state or TradingSystemState()

    app = FastAPI(
        title="AI Trader Control & Monitoring Backend",
        description=(
            "REST API backend and emergency control layer "
            "for Indian Equities Autonomous Trading System"
        ),
        version=app_config.version,
        docs_url="/docs" if app_config.api.docs_enabled else None,
        redoc_url="/redoc" if app_config.api.docs_enabled else None,
        lifespan=lifespan,
    )

    # Store configurations on app.state
    app.state.config = app_config
    app.state.system_state = app_state

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include REST API routes
    app.include_router(api_router)

    # Static UI directory configuration
    ui_path = Path(app_config.api.static_ui_dir)
    if ui_path.exists() and ui_path.is_dir():
        app.mount("/static", StaticFiles(directory=str(ui_path)), name="static")

        @app.get("/", include_in_schema=False)
        @app.get("/dashboard", include_in_schema=False)
        async def serve_dashboard() -> FileResponse:
            """Serve operator dashboard single-page web UI."""
            index_file = ui_path / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
            return FileResponse(index_file)

    else:

        @app.get("/", include_in_schema=False)
        async def root_fallback() -> JSONResponse:
            """Fallback root endpoint when UI static directory is not present."""
            return JSONResponse(
                {
                    "message": "AI Trader Control Backend API",
                    "status": "online",
                    "docs": "/docs" if app_config.api.docs_enabled else "disabled",
                }
            )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Global unhandled exception catcher logging diagnostic traces."""
        logger.exception("Unhandled error in API request", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal Server Error",
                "error": str(exc),
                "path": request.url.path,
            },
        )

    return app


# Default application instance for ASGI servers (uvicorn src.api.main:app)
app = create_app()
