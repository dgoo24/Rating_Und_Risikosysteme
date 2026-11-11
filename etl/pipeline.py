"""Pipeline entry point.

The implementation lives in ingestion.ingestion_manager; this thin entry point
keeps the documented command (`python -m etl.pipeline`) stable.
"""
from __future__ import annotations

from ingestion.ingestion_manager import main, run_pipeline

__all__ = ["main", "run_pipeline"]

if __name__ == "__main__":
    main()
