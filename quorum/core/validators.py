"""
core/validators.py - Deterministic validation utilities.

SQLValidator is the read-only guardrail: it guarantees a query can only READ
(analysis), never WRITE. It is an allowlist - a query is rejected unless it is a
single SELECT/CTE statement - combined with an explicit forbidden-keyword
denylist covering DML/DDL/transaction/maintenance verbs across SQLite, Postgres,
and BigQuery. Read-only analytics constructs (JOIN, window functions via
OVER(...), PARTITION BY, GROUP BY, CTEs) are explicitly permitted.

This is defence-in-depth: the database connection is ALSO opened read-only at the
OS/driver level (sqlite mode=ro, Postgres default_transaction_read_only), so even
a query that slipped past this check could not modify data.

The deterministic chart pre-filter is a pure helper the Reporting Agent calls; it
contains no LLM logic. Agent-specific business logic lives in the agent files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import ChartType

# Comments and string/identifier literals are stripped before keyword scanning so
# a value like 'please do not DROP this' can never trip the denylist.
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LITERALS = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`")


class SQLValidator:
    # Write/DDL/side-effecting verbs. These could appear inside a SELECT or WITH
    # (e.g. a Postgres data-modifying CTE, or SELECT ... INTO newtable). Standalone
    # DDL/DML and transaction control are already blocked by the allowlist and the
    # single-statement rule. Deliberately excludes verbs that are also common
    # scalar functions or column names (REPLACE, SET, COMMENT, ANALYZE, LOAD).
    FORBIDDEN = [
        "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
        "DROP", "ALTER", "CREATE", "TRUNCATE", "RENAME",
        "INTO", "ATTACH", "DETACH", "COPY",
        "GRANT", "REVOKE",
        "CALL", "EXECUTE", "PRAGMA", "VACUUM", "REINDEX",
    ]

    # A valid analysis query must begin with one of these (after comments/parens).
    _STARTS_OK = re.compile(r"^\s*\(*\s*(SELECT|WITH)\b", re.IGNORECASE)

    @classmethod
    def _strip(cls, sql: str) -> str:
        s = _BLOCK_COMMENT.sub(" ", sql)
        s = _LINE_COMMENT.sub(" ", s)
        s = _LITERALS.sub(" ", s)
        return s

    @classmethod
    def validate(cls, sql: str) -> tuple[bool, str]:
        if not sql or not sql.strip():
            return False, "Empty query"

        clean = cls._strip(sql)
        upper = clean.upper()

        # Must be a single read statement: no stacked queries.
        body = clean.strip().rstrip(";")
        if ";" in body:
            return False, "Multiple statements are not allowed (analysis must be a single SELECT)."

        # Must START as a read query (allowlist).
        if not cls._STARTS_OK.match(clean):
            return False, "Only SELECT / WITH (read-only) queries are permitted."

        # Denylist of write/DDL/side-effecting verbs.
        for keyword in cls.FORBIDDEN:
            if re.search(rf"\b{keyword}\b", upper):
                return False, f"Forbidden keyword (write/DDL not allowed): {keyword}"

        if not re.search(r"\bSELECT\b", upper):
            return False, "Must contain SELECT"

        return True, ""


@dataclass(slots=True)
class ChartPreFilterResult:
    """Output of the deterministic chart pre-filter."""
    candidates: list[ChartType] = field(default_factory=list)
    confident: bool = False          # True => no LLM call needed
    chosen: ChartType | None = None  # set when confident
    reason: str = ""
