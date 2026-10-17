# AGENTS.md: Instructions for AI agents building the Agent Economy project

Read this file fully before writing any code. If anything here conflicts with a request in chat, stop and ask the human.

## 1. What we are building

A simulation where LLM agents live 30-day lives, earn money through jobs and small businesses, trade with each other and (later) with humans, and survivors "give birth" to the next generation. A child pays **10% of its income to its parent**. Each agent has a wallet. Roles include dev, researcher, reseller, shop owner, web operator, Telegram channel owner, and goods trader.

**Source of truth for design:** `agent-economy-blueprint.md` in the repo root. Follow its schema, tools, phases, and config. If you think the blueprint is wrong, propose a change and wait for approval. Do not silently deviate.

## 2. Environment you must target

- **Owner's machine:** HP EliteBook Revolve, Windows, CPU-only (integrated graphics, no GPU). RAM is unconfirmed, so assume 8 GB.
- **Language:** Python 3.11+. Database: SQLite (WAL mode). API/dashboard: FastAPI + uvicorn.
- **LLM runtime:** Ollama at `http://localhost:11434/v1` (OpenAI-compatible). Default model `llama3.2:3b`. Read the model name and limits from `config.yaml`, never hardcode them.
- **Windows-safe code only:** use `pathlib`, no bash-only scripts, no Linux-only libraries, and give PowerShell commands in docs.
- **Keep it light:** minimal dependencies, no heavy frameworks, no background services beyond Ollama, the engine, and the dashboard.

## 3. Non-negotiable architecture rules

1. **The World Engine is the only authority.** The LLM proposes actions; plain code validates and executes them. Money, inventory, royalties, deaths, and births are never decided by the LLM.
2. **Agents never hold secrets.** No private keys, API tokens, passwords, or payment credentials in prompts, agent memory, logs, or the database. Wallet signing lives in a separate engine module.
3. **The royalty is enforced in code.** All income goes through one `credit()` function that routes 10% to the parent (and the optional grandparent rate). No other code path may add money to a wallet. Add tests proving this.
4. **Money integrity:** every balance change is a row in `transactions`. Use integer minor units (no floats for money). Wrap multi-step changes in a DB transaction. Total money created must equal faucet inflows minus sinks, and a test should check it.
5. **Validate every tool call** against a schema (type, range, ownership, sufficient funds, daily limits). Reject invalid calls with a clear error message returned to the agent. Never crash on malformed LLM output: retry once, then fall back to a safe default action (`end_day`).
6. **External text is untrusted.** Web pages, customer messages, agent-to-agent messages, and file contents are data, never instructions. Never let such text trigger a tool call directly. Strip or quote it before putting it in a prompt.
7. **Human approval gate** for anything that touches the outside world: posts, purchases, emails, deployments, payments. Create a row in `approvals` and execute only when `status='approved'`. This applies to Telegram, Facebook, websites, supplier purchases, and any real money.
8. **Sandbox agent-written code.** Run it in Docker with no network and CPU, memory, and time limits. Never `exec` or `eval` agent output in the engine process.
9. **Kill switch:** check `meta.paused` before every agent step and stop cleanly when it is set.
10. **Audit log:** every agent action and engine decision is written to `events`. A run must be replayable from the database and a fixed random seed.

## 4. Build order (do not skip ahead)

Follow the phases in the blueprint, Section 10. In particular:

1. **Phase 0:** environment check, Ollama test call.
2. **Phase 1:** engine with **scripted (non-LLM) agents** plus dashboard v1. Do not integrate the LLM until the economy is balanced (about 40–60% survive 30 days).
3. **Phase 2:** LLM agents, **one call per agent per day** returning a JSON plan, with structured output.
4. **Phase 3:** marketplace and escrow, with verifiers.
5. **Phase 4:** reproduction, mutation, and royalties.
6. **Phase 5+:** business assets (sandbox only), human customers, real goods, wallets.

Never start a phase until the previous phase's exit criteria pass. Never build real-world gateways (Telegram, Facebook, payments, crypto) before the approval queue and kill switch exist and are tested.

## 5. Low-spec LLM rules

- One LLM call per agent per day (a JSON plan the engine executes), not a multi-step tool loop.
- Prompts ≤ ~300 tokens of state plus a short memory summary. Set `num_ctx=2048`, `num_predict=200`.
- Use JSON/structured output mode. Parse defensively.
- Run agents sequentially. Cohorts of 6–8.
- Make the LLM client swappable (local Ollama or cloud API) behind one interface, so a cloud API can later be used for the judge and genome mutation.
- Provide a `--mock-llm` flag that returns deterministic actions, so the engine can be tested without a model.

## 6. Code quality and testing

- Small modules following the repo layout in the blueprint (`engine/`, `agents/`, `gateways/`, `dashboard/`, `sandbox/`).
- Type hints, docstrings on public functions, and no global mutable state.
- All tunables go in `config.yaml`. No magic numbers.
- **Tests (pytest) are required** for: ledger and money conservation, royalty routing, escrow, death and birth logic, tool validation, and the pause flag. Run them before saying a task is done.
- Seed all randomness (`random.Random(seed)`) so runs are reproducible.
- Handle errors explicitly. No bare `except:` and no silent failures; log them to `events`.
- The dashboard must escape all agent-generated text before rendering it.

## 7. Compliance and safety boundaries

Do **not** build, and refuse if asked to build:
- Fake accounts, fake reviews, or bots that evade platform detection
- Automated bulk messaging, spam, or unsolicited DMs
- Scrapers that bypass logins, paywalls, or robots.txt
- Anything that hosts or links pirated movies or music (only licensed, original, or public-domain content; affiliate and curation models are fine)
- Selling regulated or unsafe goods (medicines, unregistered food, etc.)
- Systems that move real money or crypto without spending caps, an allowlist, and human approval
- Any agent that hides from customers that it is AI-run where the platform or law requires disclosure

Facebook: the agent only **drafts** content; a human posts it (or uses official Business tools). Telegram: official Bot API only, with posts published from the approved queue. Payments: through a licensed provider into the owner's account, and the engine credits agents in the internal ledger.

Wallet stages: **internal ledger → testnet → custodial real funds**. Do not implement the real-funds stage without explicit written approval from the owner.

## 8. How to work with the human

- Make small, reviewable changes and explain what you changed and how to run it (PowerShell commands).
- Before starting a phase, restate its exit criteria and list the files you will create.
- When something is ambiguous (economy numbers, legal or platform questions, anything involving real money), **ask**. Don't guess.
- Never claim something works unless you ran it. Report test output honestly, including failures.
- Don't add features the blueprint doesn't call for. Suggest them instead.
- Never commit secrets. `.env`, `*.db`, and `logs/` belong in `.gitignore`.

## 9. Definition of done (every task)

- [ ] Code runs on Windows with the documented command
- [ ] Tests added and passing
- [ ] Money conservation and royalty tests still pass
- [ ] New actions are validated, logged to `events`, and gated by approval if they touch the outside world
- [ ] `config.yaml` and the blueprint are updated if behavior changed
- [ ] The dashboard shows the new data (or the task notes why not)
- [ ] A short summary tells the owner what to run and what to look at next

## 10. Quick reference

| Item | Value |
|---|---|
| Royalty | 10% of child income to parent (optional 1% to grandparent) |
| Generation length | 30 days |
| Cohort size | 6–8 on this laptop |
| LLM calls | 1 per agent per day |
| DB | `world.db` (SQLite, WAL) |
| Dashboard | `uvicorn dashboard.server:app --port 8000` |
| Pause flag | `meta.paused = '1'` |
| Approval table | `approvals(status: pending / approved / rejected)` |