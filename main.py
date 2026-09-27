"""
main.py
Bob CodeGuard — application entry point.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

from codeguard.api.routes import router
from codeguard.core.config import get_settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Bob CodeGuard",
    description="AI-powered engineering workflow — Bug Fix · PR Review · PR Detective · Doc Sync",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes (must be registered BEFORE catch-all) ─────────────────────────
app.include_router(router)

# ── Frontend static assets ────────────────────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent / "frontend" / "public"
STATIC_DIR = FRONTEND_DIR / "static"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>Bob CodeGuard</h1><p>Frontend not found. Run from project root.</p>")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str) -> FileResponse:
    """Serve frontend SPA for any non-API path."""
    # Never intercept API paths (already handled above, but guard anyway)
    if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    file_path = FRONTEND_DIR / full_path
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))
    # Fall back to SPA index
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    from fastapi import HTTPException
    raise HTTPException(status_code=404)


# ── Dev entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    cfg = get_settings()
    logger.info("Starting Bob CodeGuard on http://%s:%s", cfg.host, cfg.port)
    uvicorn.run("main:app", host=cfg.host, port=cfg.port, reload=True, log_level=cfg.log_level.lower())
