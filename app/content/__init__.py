"""Content engine: the stocked shelf of copy-ready posts and canonical answers.

Public surface used by the pipeline, planner, and dashboard. Import submodules lazily
where heavy deps (Anthropic, LanceDB) would otherwise load at import time.
"""
from app.content import engine, opportunities, queue

__all__ = ["engine", "opportunities", "queue"]
