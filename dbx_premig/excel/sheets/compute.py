"""Compute: Clusters, InstancePools, ClusterPolicies, SQLWarehouses, Libraries."""

from __future__ import annotations

from dbx_premig.excel.sheets.common import assessed_columns, yes_no
from dbx_premig.excel.types import Column, SheetSpec

__all__ = ["CLUSTERS", "CLUSTER_POLICIES", "INSTANCE_POOLS", "LIBRARIES", "SQL_WAREHOUSES"]

N = "#,##0"

CLUSTERS = SheetSpec(
    name="Clusters",
    title="Clusters  ·  all-purpose compute",
    description=(
        "All-purpose clusters (job and pipeline clusters are ephemeral and covered by Jobs / "
        "DLTPipelines). Each maps to a Fabric Environment + Spark pool."
    ),
    columns=[
        Column("Cluster id", "cluster_id", 22),
        Column("Name", "name", 28),
        Column("Source", "source", 9),
        Column("State", "state", 12),
        Column("Runtime", "runtime", 26),
        Column("Node type", "node_type", 20),
        Column("Driver node type", "driver_node_type", 20),
        Column("Workers", "workers", 16),
        Column("Auto-terminate (min)", "autotermination_min", 12, numeric=True, number_format=N),
        Column("Access mode", "access_mode", 18),
        Column("Photon", yes_no("photon"), 8),
        Column("Init scripts", "init_scripts", 8, numeric=True, number_format=N),
        Column("Docker", yes_no("docker"), 8),
        Column("GPU", yes_no("gpu"), 6),
        Column("Spark confs", "spark_conf", 8, numeric=True, number_format=N),
        Column("Databricks-only confs", "databricks_conf", 11, numeric=True, number_format=N),
        Column("Custom tags", "custom_tags", 8, numeric=True, number_format=N),
        Column("Policy id", "policy_id", 18),
        Column("Creator", "creator", 24),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.clusters,
    readiness_column="Readiness",
)

INSTANCE_POOLS = SheetSpec(
    name="InstancePools",
    title="Instance pools",
    description="Pools of idle VMs; Fabric starter pools / custom pools replace them.",
    columns=[
        Column("Pool id", "pool_id", 26),
        Column("Name", "name", 28),
        Column("Node type", "node_type", 20),
        Column("Min idle", "min_idle", 9, numeric=True, number_format=N),
        Column("Max capacity", "max_capacity", 10, numeric=True, number_format=N),
        Column(
            "Idle auto-terminate (min)",
            "idle_autotermination_min",
            13,
            numeric=True,
            number_format=N,
        ),
        Column("Preloaded runtimes", "preloaded_runtimes", 36),
        Column("State", "state", 10),
    ],
    rows=lambda r: r.estate.instance_pools,
)

CLUSTER_POLICIES = SheetSpec(
    name="ClusterPolicies",
    title="Cluster policies",
    description="Compute policies; Fabric governs compute through capacity and workspace settings.",
    columns=[
        Column("Policy id", "policy_id", 22),
        Column("Name", "name", 32),
        Column("Policy family", "family", 18),
        Column("Rules", "rules", 8, numeric=True, number_format=N),
        Column("Creator", "creator", 26),
        Column("Created", "created_at", 16),
    ],
    rows=lambda r: r.estate.cluster_policies,
)

SQL_WAREHOUSES = SheetSpec(
    name="SQLWarehouses",
    title="SQL warehouses",
    description=(
        "Databricks SQL warehouses. Fabric Warehouse speaks T-SQL, so SQL written for these "
        "warehouses needs dialect review."
    ),
    columns=[
        Column("Warehouse id", "warehouse_id", 18),
        Column("Name", "name", 28),
        Column("Size", "size", 10),
        Column("Type", "warehouse_type", 10),
        Column("Serverless", yes_no("serverless"), 10),
        Column("Min clusters", "min_clusters", 9, numeric=True, number_format=N),
        Column("Max clusters", "max_clusters", 9, numeric=True, number_format=N),
        Column("Auto stop (min)", "auto_stop_min", 9, numeric=True, number_format=N),
        Column("Photon", yes_no("photon"), 8),
        Column("Channel", "channel", 22),
        Column("State", "state", 10),
        Column("Creator", "creator", 24),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.warehouses,
    readiness_column="Readiness",
)

LIBRARIES = SheetSpec(
    name="Libraries",
    title="Libraries  ·  installed on clusters",
    description=(
        "Libraries installed on clusters, de-duplicated; they move to a Fabric Environment."
    ),
    columns=[
        Column("Kind", "kind", 12),
        Column("Library", "name", 56),
        Column("Clusters", "clusters", 9, numeric=True, number_format=N),
        Column("Cluster names", "cluster_names", 40),
        *assessed_columns(),
    ],
    rows=lambda r: r.estate.libraries,
    readiness_column="Readiness",
)
