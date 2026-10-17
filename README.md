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

Phase 1 provides a scripted simulation and dashboard. It does not call Ollama;
LLM-driven decisions remain gated on the Phase 1 economy-survival exit criterion.

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

Open http://localhost:8000 for the local dashboard. Keep it on localhost and
keep real-world actions behind human approval; agents must never receive
credentials or direct access to external APIs.
