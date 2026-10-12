"""Databricks feature -> Fabric support knowledge base (data in ``data/*.yaml``)."""

from __future__ import annotations

from dbx_premig.catalog.loader import Catalog, FeatureEntry, load_catalog

__all__ = ["Catalog", "FeatureEntry", "load_catalog"]
