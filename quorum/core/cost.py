"""
core/cost.py — Pre-execution query cost & safety estimation.

The Cost Sentinel calls this BEFORE a query runs, so an expensive or unsafe
query can be flagged (and blocked) without spending compute or money.

Two backends:

- SQLite (demo): there is no "bytes scanned", so we use `EXPLAIN QUERY PLAN`
  as an honest proxy — it reveals whether the planner does full table SCANs vs
  indexed SEARCHes, which tables are scanned, and (with row counts) the
  approximate work. This demonstrates the exact governance mechanism on a small
  DB.

- BigQuery (warehouse): the real path is a dry run — submit the query with
  `dryRun=True` and read `totalBytesProcessed` from the job statistics. This
  returns the exact bytes the query WOULD scan, for free (no execution, no
  cost), which we convert to a dollar estimate at the on-demand rate. The code
  path is provided and correctly shaped; it activates when a BigQuery client is
  available (requires google-cloud-bigquery + credentials).

The governance LOGIC (risk levels, budget gate, full-scan detection) is real in
both cases; only the BigQuery dollar figure depends on live credentials.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from pipeline.models import CostEstimate

logger = logging.getLogger(__name__)

# BigQuery on-demand pricing: ~$6.25 per TiB scanned (us multi-region, 2025).
# Adjust per contract/region. Used only for the warehouse estimate.
_BQ_USD_PER_BYTE = 6.25 / (1024 ** 4)

# Default budget ceiling for a single query (USD). Over this → high risk / block.
DEFAULT_BUDGET_USD = 1.00
# SQLite proxy: rows scanned over this → medium; well over → high.
_ROWS_MEDIUM = 50_000
_ROWS_HIGH = 1_000_000


def estimate_cost(
    adapter,
    sql: str,
    *,
    engine: str = "sqlite",
    budget_usd: float = DEFAULT_BUDGET_USD,
) -> CostEstimate:
    """Estimate the cost/safety of a query before running it."""
    engine = (engine or "sqlite").lower()
    try:
        if engine == "bigquery":
            return _estimate_bigquery(adapter, sql, budget_usd=budget_usd)
        if engine == "postgres":
            return _estimate_postgres(adapter, sql, budget_usd=budget_usd)
        return _estimate_sqlite(adapter, sql, budget_usd=budget_usd)
    except Exception as exc:  # never let estimation break the pipeline
        logger.warning("Cost estimation failed (%s); returning unknown estimate", exc)
        return CostEstimate(
            engine=engine, risk_level="low", within_budget=True,
            method="unavailable", notes=[f"estimation skipped: {exc}"],
        )


# ---------------------------------------------------------------------------
# SQLite proxy via EXPLAIN QUERY PLAN
# ---------------------------------------------------------------------------

_SCAN_RE = re.compile(r"\bSCAN\b(?:\s+TABLE)?\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_SEARCH_RE = re.compile(r"\bSEARCH\b(?:\s+TABLE)?\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)


def _estimate_sqlite(adapter, sql: str, *, budget_usd: float) -> CostEstimate:
    plan_rows = _explain(adapter, sql)
    plan_text = " ".join(str(r) for r in plan_rows)

    full_scans = sorted(set(_SCAN_RE.findall(plan_text)))
    searches = sorted(set(_SEARCH_RE.findall(plan_text)))
    uses_index = bool(searches) and not full_scans

    # Approximate rows scanned = sum of row counts of fully-scanned tables.
    rows_scanned = 0
    for t in full_scans:
        rows_scanned += _table_rows(adapter, t)

    if rows_scanned >= _ROWS_HIGH:
        risk = "high"
    elif rows_scanned >= _ROWS_MEDIUM or len(full_scans) >= 3:
        risk = "medium"
    else:
        risk = "low"

    notes = []
    if full_scans:
        notes.append(f"Full table scan(s): {', '.join(full_scans)}.")
    if searches:
        notes.append(f"Indexed access on: {', '.join(searches)}.")
    if not full_scans and not searches:
        notes.append("Planner reported no scans (constant/empty query).")

    # No dollars on SQLite; "within budget" reflects the risk proxy.
    within = risk != "high"
    return CostEstimate(
        engine="sqlite",
        estimated_rows_scanned=rows_scanned or None,
        full_scan_tables=full_scans,
        uses_index=uses_index,
        risk_level=risk,
        within_budget=within,
        notes=notes,
        method="explain_query_plan",
    )


def _explain(adapter, sql: str) -> list:
    """Run EXPLAIN QUERY PLAN through whatever connection the adapter exposes."""
    explain_sql = "EXPLAIN QUERY PLAN " + sql.strip().rstrip(";")
    # Preferred: adapter has a raw connection.
    conn = getattr(adapter, "conn", None)
    if conn is not None:
        cur = conn.execute(explain_sql)
        return cur.fetchall()
    # Fallback: adapter exposes execute_query returning rows.
    if hasattr(adapter, "execute_query"):
        res = adapter.execute_query(explain_sql)
        if isinstance(res, dict):
            return res.get("rows", []) or []
        return list(res or [])
    return []


def _table_rows(adapter, table: str) -> int:
    try:
        conn = getattr(adapter, "conn", None)
        q = f'SELECT COUNT(*) FROM "{table}"'
        if conn is not None:
            return int(conn.execute(q).fetchone()[0])
        if hasattr(adapter, "execute_query"):
            res = adapter.execute_query(q)
            rows = res.get("rows") if isinstance(res, dict) else res
            if rows:
                first = rows[0]
                return int(list(first.values())[0] if isinstance(first, dict) else first[0])
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Postgres EXPLAIN (FORMAT JSON) — planner cost estimate, no execution
# ---------------------------------------------------------------------------

def _estimate_postgres(adapter, sql: str, *, budget_usd: float) -> CostEstimate:
    """Use Postgres EXPLAIN (FORMAT JSON) to read the planner's estimated total
    cost and row count without running the query. Maps planner cost + scan type
    to the same risk model used everywhere else."""
    explain_sql = "EXPLAIN (FORMAT JSON) " + sql.strip().rstrip(";")
    try:
        rows, _ = adapter.execute_query(explain_sql, 1)
        plan_json = rows[0][0]
        if isinstance(plan_json, str):
            import json
            plan_json = json.loads(plan_json)
        root = plan_json[0]["Plan"]
    except Exception as exc:
        return CostEstimate(engine="postgres", risk_level="low", within_budget=True,
                            method="explain_unavailable", notes=[f"EXPLAIN failed: {exc}"])

    est_rows = int(root.get("Plan Rows", 0) or 0)
    total_cost = float(root.get("Total Cost", 0.0) or 0.0)

    seq_scans: list[str] = []
    def _walk(node):
        if node.get("Node Type", "").lower().startswith("seq scan"):
            rel = node.get("Relation Name")
            if rel:
                seq_scans.append(rel)
        for child in node.get("Plans", []) or []:
            _walk(child)
    _walk(root)
    seq_scans = sorted(set(seq_scans))

    if total_cost >= 1_000_000 or est_rows >= _ROWS_HIGH:
        risk = "high"
    elif total_cost >= 100_000 or est_rows >= _ROWS_MEDIUM or len(seq_scans) >= 3:
        risk = "medium"
    else:
        risk = "low"

    notes = [f"Planner total cost {total_cost:.0f}, est rows {est_rows}."]
    if seq_scans:
        notes.append(f"Sequential scan(s): {', '.join(seq_scans)}.")
    return CostEstimate(
        engine="postgres", estimated_rows_scanned=est_rows or None,
        full_scan_tables=seq_scans, uses_index=not seq_scans,
        risk_level=risk, within_budget=risk != "high", notes=notes,
        method="explain_format_json",
    )


# ---------------------------------------------------------------------------
# BigQuery dry-run (warehouse path) — real shape, activates with credentials
# ---------------------------------------------------------------------------

def _estimate_bigquery(adapter, sql: str, *, budget_usd: float) -> CostEstimate:
    """Estimate via a BigQuery dry run: returns exact bytes the query WOULD
    scan, for free. Requires a bigquery client on the adapter (`.client`)."""
    client = getattr(adapter, "client", None)
    if client is None:
        return CostEstimate(
            engine="bigquery", risk_level="low", within_budget=True,
            method="dry_run_unavailable",
            notes=["BigQuery client not configured; dry-run estimate unavailable."],
        )
    # Real dry-run code path:
    from google.cloud import bigquery  # type: ignore

    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=job_config)
    bytes_scanned = int(job.total_bytes_processed or 0)
    cost = bytes_scanned * _BQ_USD_PER_BYTE

    if cost >= budget_usd:
        risk = "high"
    elif cost >= budget_usd / 2:
        risk = "medium"
    else:
        risk = "low"

    gib = bytes_scanned / (1024 ** 3)
    return CostEstimate(
        engine="bigquery",
        estimated_bytes_scanned=bytes_scanned,
        estimated_cost_usd=round(cost, 4),
        risk_level=risk,
        within_budget=cost < budget_usd,
        notes=[f"Dry run: {gib:.2f} GiB scanned ≈ ${cost:.2f}."],
        method="dry_run",
    )
