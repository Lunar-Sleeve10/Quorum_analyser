"""
core/parsers.py — LLM response parsing utilities.

Pure functions, no LLM or Band knowledge.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


class LLMResponseParser:
    @staticmethod
    def extract_json(response_text: Optional[str]) -> Optional[dict[str, Any]]:
        if not response_text or not isinstance(response_text, str):
            return None

        cleaned = re.sub(r"```json\s*|\s*```", "", response_text).strip()
        json_match = re.search(r"\{(?:[^{}]|\{[^{}]*\})*\}", cleaned, re.DOTALL)
        if not json_match:
            return None

        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

    @staticmethod
    def extract_sql(response_text: Optional[str]) -> str:
        if not response_text:
            return "SELECT 'Error' AS error;"

        code_block = re.search(
            r"```(?:sql)?\s*(.*?)```", response_text, re.IGNORECASE | re.DOTALL
        )
        if code_block:
            sql = code_block.group(1).strip()
            if len(sql) > 10:
                return sql.rstrip(";") + ";"

        select = re.search(
            r"((?:WITH|SELECT)\s+.*?;)", response_text, re.IGNORECASE | re.DOTALL
        )
        if select:
            return select.group(1).strip()

        return "SELECT 'No valid SQL found' AS error;"
