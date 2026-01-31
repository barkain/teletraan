"""Task scheduler package for ETL orchestration.

This package provides scheduled data fetching and processing for:
- Stock price updates from Yahoo Finance
- Economic indicators from FRED
- Analysis pipeline execution
"""

from scheduler.etl import ETLOrchestrator, etl_orchestrator

__all__ = ["ETLOrchestrator", "etl_orchestrator"]
