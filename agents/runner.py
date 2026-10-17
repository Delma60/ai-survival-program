"""Phase 1/2 agent runner: scripted, mock-LLM, or real LLM decisions."""

import argparse
import random
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

from engine.db import DB_PATH
from engine.restart import RestartRefused, reset_world
from engine.scheduler import DEFAULT_CONFIG, load_config, run_generation

PathLike = Union[str, Path]


def mock_llm_decision(state: Dict[str, Any], rng: random.Random) -> str:
    """Return a deterministic action for exercising the LLM interface."""
    del rng
    return "work" if state["open_jobs"] else "end_day"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one agent generation.")
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
        "--restart",
        action="store_true",
        help="archive and wipe the world before starting a fresh generation",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock-llm",
        action="store_true",
        help="deterministic decision interface; no model is called",
    )
    mode.add_argument(
        "--llm",
        action="store_true",
        help="ask the configured Ollama model for each daily plan",
    )
    args = parser.parse_args(argv)

    if args.restart:
        try:
            result = reset_world(args.db)
        except RestartRefused as exc:
            print("Refused: {}".format(exc))
            return 1
        print("World restarted. Archive: {}".format(result["archive"]))

    policy = None
    if args.mock_llm:
        policy = mock_llm_decision
    elif args.llm:
        from agents.llm_client import OllamaClient
        from agents.policy import make_llm_policy

        config = load_config(args.config)
        llm_config = config.get("llm", {})
        policy = make_llm_policy(
            OllamaClient(config),
            retries=int(llm_config.get("retries", 1)),
            max_note_chars=int(llm_config.get("max_note_chars", 200)),
        )

    summary = run_generation(args.config, args.db, args.seed, policy)
    print(
        "Generation {generation}: {alive_agents}/{total_agents} alive "
        "({survival_rate:.0%}), status={status}".format(**summary)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
