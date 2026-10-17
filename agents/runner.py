"""Phase 1 scripted agents and their deterministic mock-LLM interface."""

import argparse
import random
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from engine.db import DB_PATH
from engine.scheduler import DEFAULT_CONFIG, run_generation

PathLike = Union[str, Path]


def mock_llm_decision(state: Dict[str, Any], rng: random.Random) -> str:
    """Return a deterministic action for exercising the future LLM interface."""
    del rng
    return "work" if state["open_jobs"] else "end_day"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one scripted agent generation.")
    parser.add_argument("--seed", type=int, default=0, help="reproducible run seed")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="YAML config path (defaults to config.yaml)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="SQLite database path (defaults to world.db)",
    )
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="use the deterministic decision interface; no model is called",
    )
    args = parser.parse_args(argv)
    policy = mock_llm_decision if args.mock_llm else None
    summary = run_generation(args.config, args.db, args.seed, policy)
    print(
        "Generation {generation}: {alive_agents}/{total_agents} alive "
        "({survival_rate:.0%}), status={status}".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
