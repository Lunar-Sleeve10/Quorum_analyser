"""
config.py — Central configuration for Quorum.

One place controls model routing, providers, database, semantic layer, and Band
room constants. Two ways to switch where the LLMs run:

  1. Master switch  — set LLM_BACKEND={local|groq|aiml|featherless|openai} to
     route EVERY agent through one provider. This is the "switch whenever I
     want" lever.
  2. Per-agent override — leave LLM_BACKEND blank and set <AGENT>_PROVIDER
     individually (e.g. PLANNER_PROVIDER=aiml, SQL_ANALYST_PROVIDER=ollama).

See AIML_INTEGRATION.md for the AI/ML API setup steps.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    GROQ = "groq"
    AIML = "aiml"             # AI/ML API (aimlapi.com) — partner credits
    FEATHERLESS = "featherless"
    OPENAI = "openai"


class DatabaseType(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
    MYSQL = "mysql"
    BIGQUERY = "bigquery"


class QueryIntent(str, Enum):
    DESCRIPTIVE = "descriptive"   # "what / how many / top N" -> governed SQL path
    DIAGNOSTIC = "diagnostic"     # "why does A differ from B" -> investigation fork/join
    UNCLEAR = "unclear"           # needs clarification


class ExecutionMode(str, Enum):
    DIRECT_SQL = "direct_sql"
    LIGHT_PLAN = "light_plan"
    FULL_PLAN = "full_plan"


class ReviewMethod(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"


class IssueType(str, Enum):
    EMPTY_RESULT = "empty_result"
    WRONG_AGGREGATION = "wrong_aggregation"
    MISSING_LIMIT = "missing_limit"
    MISSING_ORDER = "missing_order"
    NULL_HEAVY = "null_heavy"
    OTHER = "other"


class ChartType(str, Enum):
    PIE = "pie"
    BAR = "bar"
    HORIZONTAL_BAR = "horizontal_bar"
    LINE = "line"
    SCATTER = "scatter"
    STACKED_BAR = "stacked_bar"
    GROUPED_BAR = "grouped_bar"
    NONE = "none"


# ---------------------------------------------------------------------------
# Default model names per provider. Override any with <AGENT>_MODEL env vars.
# ---------------------------------------------------------------------------

class ModelNames:
    # Reasoning agents (Planner, Adjudicator, Decision Reporter) — default Groq.
    PLANNER = "groq/llama-3.1-8b-instant"
    ADJUDICATOR = "groq/llama-3.3-70b-versatile"
    REPORTER = "groq/llama-3.1-8b-instant"
    GUARDIAN = "groq/llama-3.1-8b-instant"

    # SQL generation — local code model by default, cloud fallback.
    SQL_ANALYST_LOCAL = "qwen2.5-coder:7b"
    SQL_ANALYST_CLOUD = "groq/llama-3.3-70b-versatile"

    # AI/ML API equivalents (used when a provider is set to aiml). These are
    # OpenAI-compatible model ids served by aimlapi.com. Adjust per catalog.
    AIML_REASONING = "openai/gpt-4o-mini"
    AIML_SQL = "qwen/qwen2.5-coder-32b-instruct"

    # Featherless (featherless.ai) — OpenAI-compatible, HF-style model ids
    # (the org prefix, e.g. "openai/" or "Qwen/", is part of the real id and
    # must NOT be stripped for this endpoint). SQL gets a dedicated coder model.
    FEATHERLESS_REASONING = "openai/gpt-oss-20b"
    FEATHERLESS_SQL = "Qwen/Qwen2.5-Coder-32B-Instruct"


# ---------------------------------------------------------------------------
# Band room / channel constants
# ---------------------------------------------------------------------------

class BandConfig:
    ROOM_PREFIX = "session:"
    REGISTRY_ROOM = "system:registry"

    CHANNEL_TASKS = "tasks"
    CHANNEL_CONTROL = "control"
    CHANNEL_TELEMETRY = "telemetry"

    TOPIC_HANDOFF = "handoff"
    TOPIC_REVIEW = "review"
    TOPIC_REVISION = "revision"
    TOPIC_COMPLETION = "completion"
    TOPIC_CONTROL = "control"
    TOPIC_PLAN = "plan"
    TOPIC_INVESTIGATION = "investigation"

    # Hard caps that keep the system inside its LLM budget.
    MAX_REVISIONS = 1            # Guardian can request at most one SQL revision
    MAX_DEBATE_ROUNDS = 2        # bounded challenge/response negotiation
    MAX_REPLANS = 1              # Supervisor may revise the plan once on stall
    MAX_CLARIFICATIONS = 3
    MAX_FACTORS = 6              # cap on parallel investigators
    RESULT_SAMPLE_ROWS = 5


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )

    # --- Database ---
    db_path: str = Field(default="analytics.db", alias="DB_PATH")
    db_type: DatabaseType = Field(default=DatabaseType.SQLITE, alias="DB_TYPE")
    db_max_rows: int = Field(default=1000, alias="DB_MAX_ROWS")
    db_timeout: int = Field(default=30, alias="DB_TIMEOUT")
    db_read_only: bool = Field(default=True, alias="DB_READ_ONLY")
    # Postgres / BigQuery connection (used when db_type is set accordingly).
    pg_dsn: str = Field(default="", alias="PG_DSN")
    bq_project: str = Field(default="", alias="BQ_PROJECT")
    bq_dataset: str = Field(default="", alias="BQ_DATASET")

    # --- Semantic layer ---
    metric_catalog_path: str = Field(default="metric_catalog.yaml", alias="METRIC_CATALOG_PATH")
    schema_retrieval_k: int = Field(default=8, alias="SCHEMA_RETRIEVAL_K")

    # --- Master provider switch (blank = use per-agent providers) ---
    llm_backend: str = Field(default="", alias="LLM_BACKEND")

    # --- Per-agent providers (used when llm_backend is blank) ---
    planner_provider: LLMProvider = Field(default=LLMProvider.GROQ, alias="PLANNER_PROVIDER")
    sql_analyst_provider: LLMProvider = Field(default=LLMProvider.OLLAMA, alias="SQL_ANALYST_PROVIDER")
    guardian_provider: LLMProvider = Field(default=LLMProvider.GROQ, alias="GUARDIAN_PROVIDER")
    reporter_provider: LLMProvider = Field(default=LLMProvider.GROQ, alias="REPORTER_PROVIDER")
    adjudicator_provider: LLMProvider = Field(default=LLMProvider.GROQ, alias="ADJUDICATOR_PROVIDER")

    # --- Per-agent models (override defaults) ---
    planner_model: str = Field(default=ModelNames.PLANNER, alias="PLANNER_MODEL")
    sql_analyst_model_local: str = Field(default=ModelNames.SQL_ANALYST_LOCAL, alias="SQL_ANALYST_MODEL_LOCAL")
    sql_analyst_model_cloud: str = Field(default=ModelNames.SQL_ANALYST_CLOUD, alias="SQL_ANALYST_MODEL_CLOUD")
    guardian_model: str = Field(default=ModelNames.GUARDIAN, alias="GUARDIAN_MODEL")
    reporter_model: str = Field(default=ModelNames.REPORTER, alias="REPORTER_MODEL")
    adjudicator_model: str = Field(default=ModelNames.ADJUDICATOR, alias="ADJUDICATOR_MODEL")

    # --- API keys ---
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    aiml_api_key: str = Field(default="", alias="AIML_API_KEY")
    aiml_base_url: str = Field(default="https://api.aimlapi.com/v1", alias="AIML_BASE_URL")
    featherless_api_key: str = Field(default="", alias="FEATHERLESS_API_KEY")
    featherless_base_url: str = Field(default="https://api.featherless.ai/v1", alias="FEATHERLESS_BASE_URL")
    featherless_reasoning_model: str = Field(default=ModelNames.FEATHERLESS_REASONING, alias="FEATHERLESS_REASONING_MODEL")
    featherless_sql_model: str = Field(default=ModelNames.FEATHERLESS_SQL, alias="FEATHERLESS_SQL_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    # --- Band ---
    band_rest_url: str = Field(default="https://app.band.ai", alias="BAND_REST_URL")
    dashboard_agent_id: str = Field(default="", alias="DASHBOARD_AGENT_ID")
    dashboard_api_key: str = Field(default="", alias="DASHBOARD_API_KEY")
    use_band: bool = Field(default=False, alias="USE_BAND")

    # --- LLM behaviour ---
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=2048, alias="LLM_MAX_TOKENS")

    # --- Memory ---
    enable_memory: bool = Field(default=True, alias="ENABLE_MEMORY")
    memory_dir: str = Field(default=".quorum_memory", alias="MEMORY_DIR")

    # --- App ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("llm_temperature")
    @classmethod
    def clamp_temperature(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("llm_backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v and v not in {p.value for p in LLMProvider}:
            raise ValueError(f"LLM_BACKEND must be one of {[p.value for p in LLMProvider]} or blank")
        return v

    # ------------------------------------------------------------------
    # Provider / model resolution — the single switch point
    # ------------------------------------------------------------------

    _AGENT_PROVIDER_ATTR = {
        "planner": "planner_provider",
        "sql_analyst": "sql_analyst_provider",
        "guardian": "guardian_provider",
        "reporter": "reporter_provider",
        "adjudicator": "adjudicator_provider",
    }

    def provider_for(self, agent: str) -> LLMProvider:
        """Master switch wins; otherwise the per-agent provider."""
        if self.llm_backend:
            return LLMProvider(self.llm_backend)
        attr = self._AGENT_PROVIDER_ATTR.get(agent, "planner_provider")
        return getattr(self, attr)

    def model_for(self, agent: str) -> str:
        """Resolve the model id for an agent under its active provider."""
        provider = self.provider_for(agent)
        if agent == "sql_analyst":
            if provider == LLMProvider.OLLAMA:
                return self.sql_analyst_model_local
            if provider == LLMProvider.AIML:
                return ModelNames.AIML_SQL
            if provider == LLMProvider.FEATHERLESS:
                return self.featherless_sql_model
            return self.sql_analyst_model_cloud
        # Reasoning agents
        if provider == LLMProvider.AIML:
            return ModelNames.AIML_REASONING
        if provider == LLMProvider.FEATHERLESS:
            return self.featherless_reasoning_model
        return {
            "planner": self.planner_model,
            "guardian": self.guardian_model,
            "reporter": self.reporter_model,
            "adjudicator": self.adjudicator_model,
        }.get(agent, self.planner_model)

    def api_key_for(self, provider: LLMProvider) -> str:
        return {
            LLMProvider.GROQ: self.groq_api_key,
            LLMProvider.AIML: self.aiml_api_key,
            LLMProvider.FEATHERLESS: self.featherless_api_key,
            LLMProvider.OPENAI: self.openai_api_key,
            LLMProvider.OLLAMA: "",
        }.get(provider, "")

    def base_url_for(self, provider: LLMProvider) -> str:
        if provider == LLMProvider.OLLAMA:
            return self.ollama_base_url
        if provider == LLMProvider.AIML:
            return self.aiml_base_url
        if provider == LLMProvider.FEATHERLESS:
            return self.featherless_base_url
        return ""

    # ------------------------------------------------------------------
    # Backward-compatible accessors (specialist agents written against the
    # earlier names map onto the new role-based resolution above).
    # ------------------------------------------------------------------
    @property
    def orchestrator_provider(self) -> LLMProvider:
        return self.provider_for("planner")

    @property
    def orchestrator_model(self) -> str:
        return self.model_for("planner")

    @property
    def sql_engineer_provider(self) -> LLMProvider:
        return self.provider_for("sql_analyst")

    def sql_engineer_model(self) -> str:
        return self.model_for("sql_analyst")

    @property
    def reviewer_provider(self) -> LLMProvider:
        return self.provider_for("guardian")

    @property
    def reviewer_model(self) -> str:
        return self.model_for("guardian")

    @property
    def reporting_provider(self) -> LLMProvider:
        return self.provider_for("reporter")

    @property
    def reporting_model(self) -> str:
        return self.model_for("reporter")

    @property
    def orchestrator_mode(self) -> str:
        return "merged"

    @model_validator(mode="after")
    def warn_missing_keys(self) -> "Settings":
        import warnings
        used = {self.provider_for(a) for a in self._AGENT_PROVIDER_ATTR}
        if LLMProvider.GROQ in used and not self.groq_api_key:
            warnings.warn("GROQ provider configured but GROQ_API_KEY is not set.", stacklevel=2)
        if LLMProvider.AIML in used and not self.aiml_api_key:
            warnings.warn("AIML provider configured but AIML_API_KEY is not set.", stacklevel=2)
        return self


settings = Settings()
