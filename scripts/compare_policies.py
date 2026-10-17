"""Compare random and scripted policy survival over seeded generations.

Run from the project root:
    python scripts/compare_policies.py --seeds 20

Run an LLM generation separately with `python -m agents.runner --llm` and compare
its printed survival rate with these seeded baseline averages.
"""
import argparse
import random
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence

from engine.scheduler import DEFAULT_CONFIG, run_generation

Policy = Callable[[Dict[str, Any], random.Random], Any]


def random_policy(state: Dict[str, Any], rng: random.Random) -> str:
    """Pick work or end_day at random (work only if a job is open)."""
    if state["open_jobs"] and rng.random() < 0.5:
        return "work"
    return "end_day"


def scripted_policy(state: Dict[str, Any], rng: random.Random) -> str:
    """Always work when a job is open."""
    del rng
    return "work" if state["open_jobs"] else "end_day"


def average_survival(
    policy: Optional[Policy],
    seeds: int,
    config_path: Path,
) -> float:
    """Average survival rate over several independently seeded generations."""
    if seeds <= 0:
        raise ValueError("seeds must be positive")

    rates = []
    with tempfile.TemporaryDirectory() as tmp:
        for seed in range(seeds):
            summary = run_generation(
                config_path, Path(tmp) / "run-{}.db".format(seed), seed, policy
            )
            rates.append(summary["survival_rate"])
    return sum(rates) / len(rates)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare baseline survival rates.")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    if args.seeds <= 0:
        parser.error("--seeds must be positive")

    print(
        "random policy  : {:.0%}".format(
            average_survival(random_policy, args.seeds, args.config)
        )
    )
    print(
        "scripted policy: {:.0%}".format(
            average_survival(scripted_policy, args.seeds, args.config)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
