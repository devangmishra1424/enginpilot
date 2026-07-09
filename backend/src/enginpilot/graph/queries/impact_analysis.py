"""Graph query helpers for downstream impact analysis.

This module is a thin helper layer for the agent graph adapter. It uses a
real Neo4j connection when configured, otherwise it falls back to the same
curated mock data used by the agent-side adapter.
"""

from __future__ import annotations

from agents.tools.cypher_query import get_asset, get_downstream_assets, list_all_assets

__all__ = ["get_asset", "get_downstream_assets", "list_all_assets"]