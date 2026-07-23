"""FastAPI entry point. Serves the dashboard and its JSON API on localhost only.

Run: uvicorn app.main:app --port 4317
This process is the always-on read surface. It never collects (launchd does) and holds
no source credentials beyond what routes explicitly need.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.dashboard.routes import router

app = FastAPI(title="Radar Assistant", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    init_db()


app.include_router(router, prefix="/api")

_static = Path(__file__).resolve().parent / "dashboard" / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
