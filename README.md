# AI Survival Program

A local-first simulation where LLM agents make decisions while the World Engine
validates and executes all economy actions. See [AGENTS.md](AGENTS.md) for the
architecture, safety requirements, and phased roadmap.

## Project layout

- `engine/` — ledger, market, jobs, simulation scheduler, and validated tools
- `agents/` — model runner, genomes, and rolling memory
- `gateways/` — human-approved integrations and research access
- `dashboard/` — local progress dashboard
- `sandbox/` — isolated execution area for agent-generated code
- `sites/` — generated website output
- `logs/` — local run logs
- `tests/` — automated tests

Phase 1 provides a scripted simulation and dashboard. Phase 2 adds an optional
Ollama policy that makes one structured JSON decision per agent per day; the
engine validates and logs each decision before execution.

Phase 2 close-out tools compare seeded random and scripted survival baselines
and export the event audit log plus a per-day survival curve:

```powershell
python scripts/compare_policies.py --seeds 20
python -m agents.runner --llm --seed 42 --db world-llm.db
python scripts/export_events.py --db world-llm.db --out logs/events.csv
```

Compare the LLM runner's reported survival rate with the baseline averages.
The export command also writes `logs/survival.csv` by default; pass
`--survival-out` to choose another path.

## Development setup (Windows PowerShell)

This project requires Python 3.11 or newer. From the project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run Phase 1

From the project directory with the virtual environment active:

```powershell
python -m agents.runner --mock-llm --seed 42
python scripts/check_llm.py
python -m agents.runner --llm --seed 42 --db world-llm.db
python -m uvicorn dashboard.server:app --port 8000
```

Run the test suite from the project root with:

```powershell
python -m pytest tests -q
```

The simulation uses the 8-agent low-spec cohort, 50 starting credits per agent,
and 5 credits of daily upkeep. Jobs and their rewards are tunable under `jobs`
in `config.yaml`. `--mock-llm` exercises a deterministic decision interface and
does not call a model. The default database is `world.db`; it uses SQLite WAL
mode and is ignored by Git.

Use `--llm` only after Ollama is running with the configured model. It performs
one model request per living agent per day and can take hours on a CPU-only
machine; `scripts/check_llm.py` makes a single connectivity check first.

Open http://localhost:8000 for the local dashboard. Keep it on localhost and
keep real-world actions behind human approval; agents must never receive
credentials or direct access to external APIs.

To archive and reset the default world database to generation 1, day 1, run:

```powershell
python -m engine.restart
```

The command asks for confirmation and saves a SQLite backup under
`logs/archive/` before clearing simulation data. A running world must be paused
before it can be reset. To reset and immediately start a fresh generation:

```powershell
python -m agents.runner --restart --mock-llm --seed 42
```

The dashboard also provides a **Restart world** button. Pause the simulation
and wait for its runner process to stop before using it.
