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

The modules are scaffolded for phased implementation; the simulation is not
ready to run yet.

## Development setup (Windows PowerShell)

This project requires Python 3.11 or newer. From the project directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Simulation settings are in `config.yaml`. Keep real-world actions behind human
approval and never give agents direct access to credentials or external APIs.
