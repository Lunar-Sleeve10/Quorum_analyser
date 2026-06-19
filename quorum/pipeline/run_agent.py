"""
pipeline/run_agent.py — Launch one Quorum Band agent by role.

Run this once per role (four processes total) to bring the full multi-agent
team online in Band:

    python -m pipeline.run_agent --role supervisor
    python -m pipeline.run_agent --role sql_analyst
    python -m pipeline.run_agent --role cost_sentinel
    python -m pipeline.run_agent --role guardian
    python -m pipeline.run_agent --role decision_reporter
    python -m pipeline.run_agent --role investigator
    python -m pipeline.run_agent --role adjudicator

Each process connects as a separate remote agent using credentials from
agent_config.yaml (keyed by role) and the platform URLs from .env. The agents
coordinate in a Band chat room via @mention handoffs (see pipeline/adapter.py).

Requires the Band SDK:  pip install "band-sdk[pydantic-ai]"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from pipeline.adapter import VALID_ROLES, QuorumBandAdapter

logger = logging.getLogger(__name__)

# agent_config.yaml keys are the short role names; reporting_agent maps to
# the "reporting" config key for convenience.
ROLE_TO_CONFIG_KEY = {
    "supervisor": "supervisor",
    "sql_analyst": "sql_analyst",
    "cost_sentinel": "cost_sentinel",
    "guardian": "guardian",
    "decision_reporter": "decision_reporter",
    "investigator": "investigator",
    "adjudicator": "adjudicator",
}


def _load_band_sdk():
    try:
        from band import Agent  # type: ignore
        from band.config import load_agent_config  # type: ignore
        return Agent, load_agent_config
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "Band SDK not installed. Run:\n"
            '    pip install "band-sdk[pydantic-ai]"\n'
            f"(import error: {exc})"
        )


async def run_role(role: str) -> None:
    Agent, load_agent_config = _load_band_sdk()

    config_key = ROLE_TO_CONFIG_KEY.get(role, role)
    agent_id, api_key = load_agent_config(config_key)

    base_url = os.getenv("BAND_REST_URL") or os.getenv("THENVOI_REST_URL") or "https://app.band.ai"
    adapter = QuorumBandAdapter(role=role, api_key=api_key, base_url=base_url)

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv("THENVOI_WS_URL"),
        rest_url=os.getenv("THENVOI_REST_URL"),
    )

    logger.info("Starting Band agent role=%s (config=%s). Ctrl+C to stop.",
                role, config_key)
    await agent.run()


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="Launch one Band agent by role.")
    parser.add_argument(
        "--role",
        required=True,
        choices=sorted(VALID_ROLES),
        help="Which agent role this process runs.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_role(args.role))
    except KeyboardInterrupt:
        logger.info("Shutting down role=%s", args.role)
        sys.exit(0)


if __name__ == "__main__":
    main()
