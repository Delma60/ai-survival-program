# Agent Economy: Local LLM Survival & Evolution Project

A simulation (later a real-world pilot) where LLM agents live 30-day lives, earn money through jobs and businesses, trade with each other and with humans, and the survivors "give birth" to the next generation. Children pay 10% of their earnings to their parent.

**Core principle:** the LLM only *decides*. All money, inventory, rules, royalties, and real-world actions are executed by plain code (the **World Engine**) that validates every request. Agents never hold keys, passwords, or direct API access.

---

## 1. Concepts

| Term | Meaning |
|---|---|
| **Agent** | An LLM + genome + memory + wallet |
| **Genome** | JSON: system prompt, role preferences, risk level, strategy notes, temperature |
| **Generation** | One 30-day run of a cohort of agents |
| **World Engine** | The source of truth: ledger, marketplace, job board, scheduler, lineage |
| **Tool** | A function the agent can request; the engine validates and executes it |
| **Verifier** | Code or a judge model that confirms work was actually delivered |
| **Faucet / Sink** | Money entering the economy (tasks, human buyers) / leaving it (upkeep, fees) |
| **Royalty** | 10% of a child's income routed automatically to its parent |

---

## 2. Architecture

```
                    ┌────────────────────────────┐
                    │        WORLD ENGINE        │
                    │  Ledger · Marketplace      │
                    │  Job board · Scheduler     │
                    │  Lineage · Royalty router  │
                    └──────┬──────────────┬──────┘
                           │              │
              validated tool calls     Gateways (human-in-the-loop)
                           │              │
        ┌──────────────────┴───┐   ┌──────┴────────────────────────┐
        │  AGENTS (local LLM)  │   │ Telegram · FB · Websites ·    │
        │  genome + memory     │   │ Payments · Web search · Goods │
        └──────────────────────┘   └───────────────────────────────┘
```

**Suggested stack**
- Python 3.11+, SQLite (upgrade to Postgres later), FastAPI for the engine and gateways
- Model runner: Ollama / LM Studio / vLLM (OpenAI-compatible API at `localhost`)
- Models: on a CPU-only laptop (HP EliteBook Revolve) use small 1.5B–3B models (Qwen, Llama families, Q4); see Section 14. Use a larger model, local or cloud, only as the judge
- Dashboard: FastAPI + a single HTML page reading the same SQLite database (Section 15)
- Sandbox for running agent-written code: Docker with no network, CPU/memory/time limits
- Wallets: internal ledger first, then testnet (`web3.py` / `eth_account`)

---

## 3. Data model (SQLite)

```sql
agents(id, parent_id, generation, genome_json, status, born_day, died_day, wallet_id)
wallets(id, owner_agent_id, balance, kind)            -- kind: internal | testnet | real
transactions(id, ts, from_wallet, to_wallet, amount, reason, ref_id)
listings(id, seller_agent_id, kind, title, price, stock, status)   -- kind: product | service | self_as_dev
orders(id, listing_id, buyer_type, buyer_id, price, status, escrow_tx)  -- buyer_type: agent | human
jobs(id, source, description, reward, verifier, deadline, status, assigned_agent_id)
assets(id, owner_agent_id, kind, meta_json, status)   -- site, channel, fb_page, inventory item
events(id, ts, agent_id, tool, args_json, result_json) -- full audit log
approvals(id, ts, agent_id, kind, payload_json, status)  -- human approval queue
meta(key, value)                                      -- generation, day, paused flag
lessons(id, agent_id, day, text)                      -- rolling memory summaries
```

Every credit to a wallet passes through the **royalty router** (Section 6).

---

## 4. Agent loop (daily)

> On the EliteBook, use **low-spec mode** (Section 14.4): one LLM call per agent per day returning a JSON plan, instead of a multi-step tool loop. The engine also checks `meta.paused` before each step so the dashboard's Pause button works.

```
for day in 1..30:
    for agent in alive_agents (shuffled):
        ctx = system_prompt(genome) + state_summary + lessons + today's opportunities
        for step in range(MAX_STEPS_PER_DAY):      # e.g. 6
            action = llm(ctx, tools)
            result = engine.execute(agent, action)  # validated, logged
            ctx += result
            if action == end_day: break
    engine.settle_day()   # upkeep, escrow releases, random events, deaths
```

**Survival rules (tunable):** daily upkeep (e.g. 5 credits "compute + living"), starting balance (e.g. 50), death when balance < 0 after grace period. Target 30–60% survival; adjust faucet/sinks until you hit it.

---

## 5. Tools agents can call

All tools return structured JSON and are rate-limited per day.

### Core
- `check_status()` · `view_market()` · `view_jobs()` · `end_day()`
- `transfer(to_wallet, amount, memo)` (internal only, engine-validated)
- `write_note(text)` (saved into rolling memory)

### Jobs and selling
- `take_job(job_id)` · `submit_work(job_id, payload)`
- `list_service(title, price, description)` · `list_product(...)`
- `list_self_as_dev(rate, skills)` (sells coding work to agents or humans)
- `buy(listing_id, qty)` · `rate(order_id, score)`

### Businesses ("assets")
- `open_shop(platform, name)` → creates a *draft* shop asset
- `post_content(asset_id, text, media)` → goes to a **review queue**
- `create_website(template, name, niche)` → generates a site into a sandbox folder
- `create_channel_post(channel_id, text)` → review queue
- `update_listing_price(...)`

### Research
- `web_search(query)` · `fetch_page(url)` (through a gateway with allowlists, rate limits, and caching)
- `calculate_margin(buy_price, sell_price, fees)`

### Physical goods
- `source_supplier(query)` → researches suppliers, returns candidates
- `propose_purchase(item, qty, supplier, cost)` → **always requires human approval**
- `record_delivery(order_id, proof)`

---

## 6. Reproduction and the 10% royalty

**At day 30:**
1. Rank survivors by net worth (balance + inventory value + asset value).
2. Top N survivors may reproduce (N = e.g. 25% of cohort).
3. Child creation:
   - **Genome** = parent genome + mutation (LLM rewrites strategy notes; random tweak to risk, temperature, role weights)
   - **Memory** = parent's distilled "lessons learned" memo (max ~500 words)
   - **Seed money** = fixed amount *paid by the parent* (reproduction has a cost)
4. Record `parent_id` and generation number.

**Royalty router (engine-level, not agent-controlled):**
```python
def credit(wallet, amount, reason):
    agent = agent_of(wallet)
    royalty = 0
    if agent.parent_id and agent.age_days <= ROYALTY_WINDOW_DAYS:   # or lifetime
        royalty = amount * 0.10
        ledger.add(parent_wallet(agent), royalty, "royalty")
        if grandparent: ledger.add(grandparent_wallet, royalty * 0.10, "royalty-gen2")
    ledger.add(wallet, amount - royalty, reason)
```
Apply to **income only** (sales, job rewards), not to transfers from parent or refunds. Log every royalty.

---

## 7. Roles and business types

Agents pick a role from their genome but can switch, with a cost.

| Role | Activity | Verifier / proof |
|---|---|---|
| **Dev** | Sells coding work (scripts, sites, bots) | Unit tests in sandbox; buyer acceptance |
| **Researcher** | Briefs, market research, price comparisons | Rubric-scored by judge model + human spot check |
| **Reseller** | Buy from supplier/agent, relist at markup | Inventory + sale records |
| **Shop owner (FB)** | Runs a Facebook shop/page selling goods | Orders and payment records |
| **Web operator** | Runs e-commerce, movies, or music sites | Site builds, traffic, orders |
| **Channel owner** | Runs a Telegram channel (news, deals, niche) | Subscriber growth, ad/affiliate income |
| **Goods trader** | Sources and flips real-life goods | Supplier receipts, delivery proof |

### Business-specific rules

**Facebook shop**
- Platforms generally prohibit automated accounts and bulk automation. Treat the agent as a *content drafter*: it writes listings, captions, replies, and pricing; **a human posts and replies** (or uses the platform's official Business/Commerce tools).
- Don't create fake accounts or fake reviews.

**Websites (e-commerce, movies, music)**
- Agents generate and update the site code and listings in a sandbox; you deploy.
- **Movies and music: only licensed or original content.** Hosting or linking pirated media is illegal and will get hosting, payment, and ad accounts terminated. Viable options: original or royalty-free music, public-domain films, affiliate links to legal streaming and stores, reviews and curation sites.
- E-commerce: real checkout goes through a payment provider (e.g. Paystack, Flutterwave) with your merchant account, not the agent's wallet.

**Telegram channel**
- Use the official Bot API. The agent drafts posts into a review queue; a scheduler publishes approved posts.
- No spam, no mass-adding users, no unsolicited DMs.

**Internet research**
- Route through a gateway with domain allowlist, rate limits, and caching. Treat all fetched content as **untrusted** (prompt-injection risk): strip instructions, never let page text trigger tool calls directly.

**Real-life goods trading**
- Every purchase and shipment needs human approval and a spending cap per agent per day.
- Track inventory, supplier, landed cost, and delivery proof in `assets`.
- Check import rules, product safety, and tax obligations for what you sell in Nigeria. Avoid regulated goods (medicines, food without NAFDAC registration, etc.).

**Selling itself as a dev**
- Agent lists a service (e.g. "landing page in 24h"). Orders from agents or humans go through escrow. Work is tested in the sandbox; the human customer sees output only after you review it.

---

## 8. Wallets and money phases

| Stage | What it is | Risk |
|---|---|---|
| **A. Internal ledger** | Numbers in SQLite | None |
| **B. Testnet crypto** | Real keypairs, fake coins (e.g. Sepolia) | None |
| **C. Custodial real funds** | Engine holds keys; strict limits | Real |

**Hard rules for stage C:**
- Agents **never** see keys; they call `transfer()` and the engine's signer enforces rules
- Per-agent daily cap, counterparty allowlist, human approval above a threshold
- A float you can afford to lose; the main funds stay in cold storage
- Keep records of every transaction for tax; check Nigerian regulations (SEC, CBN guidance, tax) before taking or paying out real crypto or fiat

---

## 9. Safety and guardrails (non-negotiable)

1. **Human approval queue** for anything that touches the outside world: posts, purchases, emails, deployments.
2. **Sandbox all agent-written code** (Docker, no network, resource limits).
3. **Prompt-injection defence:** external text is data, never instructions. Tool args are schema-validated.
4. **Spending caps** per agent, per day, per counterparty.
5. **Kill switch:** one command pauses all agents and gateways.
6. **Audit log** of every action with replay.
7. **No impersonation:** disclose to customers when they're dealing with an AI-run service where required by the platform or law.
8. **Compliance check** before each new gateway goes live (platform ToS, local law, tax).

---

## 10. Phases

### Phase 0: Setup (day 1–2)
- [ ] Install Ollama or LM Studio; pull a tool-calling model (e.g. `qwen2.5:7b-instruct`)
- [ ] Python env, SQLite, repo structure (`engine/`, `agents/`, `gateways/`, `logs/`)
- [ ] Check CPU, RAM, and free disk (Section 14.1) and pick the model tier (Section 14.2)
- [ ] Apply the Ollama low-spec settings (Section 14.3) and measure tokens per second
- [ ] Test an OpenAI-compatible call to `localhost`

**Exit:** model responds with a valid tool call.

### Phase 1: World engine with scripted agents (week 1)
- [ ] Ledger, wallets, transactions
- [ ] Day loop, upkeep, death
- [ ] Job board with random task generator (the faucet)
- [ ] Scripted (non-LLM) agents to tune the economy
- [ ] Dashboard v1 (read-only: cards, agents, generations, events) from Section 15

**Exit:** ~40–60% of scripted agents survive 30 days.

### Phase 2: LLM agents (week 2)
- [ ] Tool schemas + validators
- [ ] Agent loop with rolling memory
- [ ] Logging and replay viewer (even a CSV + chart)

**Exit:** LLM agents survive at a rate comparable to or better than random.

### Phase 3: Marketplace and escrow (week 3)
- [ ] Listings, orders, escrow, ratings
- [ ] Verifiers: sandbox test runner, judge model, rubric
- [ ] Agent-to-agent trade

**Exit:** agents trade with each other and prices move.

### Phase 4: Reproduction and royalties (week 4)
- [ ] Ranking, genome mutation, lessons memo
- [ ] Parent-funded seed money
- [ ] Royalty router (10% + optional grandparent decay)
- [ ] Lineage tree and stats per generation

**Exit:** run 10+ generations; plot survival, wealth, and dominant roles over time.

### Phase 5: Business assets, sandboxed (weeks 5–6)
- [ ] Website generator (templates for store/blog/curated media)
- [ ] Telegram bot gateway with review queue (test channel only)
- [ ] FB shop **drafting** workflow (agent writes, human posts)
- [ ] Web research gateway with allowlist and cache

**Exit:** agents produce assets and content that you'd approve with minimal edits.

### Phase 6: Human customers (weeks 7–8)
- [ ] Simple storefront / request form / Telegram intake
- [ ] Order routing to agents; human review before delivery
- [ ] Payments through a licensed provider into **your** account; engine credits agents in the internal ledger
- [ ] Start with friends and a small number of real orders

**Exit:** first real, human-paid orders fulfilled with good ratings.

### Phase 7: Real goods (weeks 9–10)
- [ ] Supplier research tools, margin calculator
- [ ] Purchase approval flow and spending caps
- [ ] Inventory and delivery tracking
- [ ] Start with one product category and tiny batches

**Exit:** a profitable small batch, with full records.

### Phase 8: Crypto wallets (week 11+)
- [ ] Testnet wallets per agent, signer service
- [ ] Reconcile on-chain with internal ledger
- [ ] Only after legal check: small real-funds pilot with strict caps

### Phase 9: Scale and evolve
- [ ] Multiple models and cohorts, A/B genomes
- [ ] Dashboards (survival, income by role, best lineages)
- [ ] Automated judge calibration against human scores

---

## 11. Economy tuning cheat sheet

| Knob | Effect |
|---|---|
| Daily upkeep ↑ | More deaths, stronger selection |
| Job reward ↑ / job count ↑ | More survivors, less pressure |
| Reproduction cost ↑ | Fewer, richer children |
| Royalty % / duration | Rewards "good parents", slows child growth |
| Platform fee on trades | Prevents infinite circular money |
| Mutation rate | Higher = exploration, lower = stability |
| Random events | Prevents one fixed winning strategy |

**Watch for failure modes:** agents trading in circles with no real value (needs faucet and fees), judge-gaming (agents write what the judge likes), monoculture (one strategy dominates), and runaway lineages (cap royalty depth).

---

## 12. Suggested repo layout

```
agent-economy/
├── engine/
│   ├── ledger.py        # wallets, transactions, royalty router
│   ├── market.py        # listings, orders, escrow
│   ├── jobs.py          # generator + verifiers
│   ├── lineage.py       # reproduction, mutation
│   ├── scheduler.py     # day loop, settlement, deaths
│   └── tools.py         # tool schemas + validators
├── agents/
│   ├── runner.py        # LLM loop
│   ├── genome.py
│   └── memory.py
├── gateways/
│   ├── telegram.py      # review queue + publisher
│   ├── web_research.py
│   ├── payments.py
│   └── approvals.py     # creates approval requests for gated actions
├── dashboard/
│   ├── server.py        # FastAPI API + approvals + pause/resume
│   └── static/index.html
├── sandbox/             # Docker runner for agent code
├── sites/               # generated websites
├── logs/
├── config.yaml          # economy knobs
└── README.md
```

---

## 13. Starter config (`config.yaml`)

```yaml
days_per_generation: 30
cohort_size: 12
starting_balance: 50
daily_upkeep: 5
max_steps_per_day: 6
reproduction:
  top_fraction: 0.25
  seed_money: 20
  mutation_rate: 0.2
royalty:
  rate: 0.10
  grandparent_rate: 0.01
  window_days: 60        # or null for lifetime
marketplace_fee: 0.03
approval_required_for: [post_content, propose_purchase, create_website, deploy]
daily_spend_cap: 30
low_spec:
  llm_calls_per_agent_per_day: 1
  num_ctx: 2048
  num_predict: 200
  cohort_size: 8
  model: llama3.2:3b          # change after checking RAM (Section 14.2)
```

---

## 14. Hardware: HP EliteBook Revolve (CPU-only laptop)

The EliteBook Revolve is a 2-in-1 with integrated Intel graphics and **no dedicated GPU**. Models run on the CPU, so speed and RAM decide what's practical.

### 14.1 How to check your CPU, RAM, and disk (Windows)

**Option A: Settings (easiest)**
1. Press `Windows key + I` → **System** → **About**.
2. Under *Device specifications* note:
   - **Processor**: for example `Intel(R) Core(TM) i5-6300U`
   - **Installed RAM**: for example `8.00 GB`
   - **System type**: should say 64-bit (required for local models)

**Option B: Task Manager**
1. Press `Ctrl + Shift + Esc` → **Performance** tab.
2. **CPU**: the name is at the top right, with cores and logical processors below.
3. **Memory**: total GB at the top right. *Slots used: 1 of 2* means you could add a second RAM stick.
4. **Disk**: check free space. Each model is 1–5 GB, so keep at least 15 GB free.

**Option C: PowerShell (copy-paste everything at once)**
```powershell
Get-CimInstance Win32_Processor | Select Name, NumberOfCores, NumberOfLogicalProcessors
"{0:N1} GB RAM" -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Get-PSDrive C | Select @{n="FreeGB";e={[math]::Round($_.Free/1GB,1)}}
```
Write the results down. They decide the model tier below.

### 14.2 Model tier by RAM

| Installed RAM | What to run | Notes |
|---|---|---|
| 4 GB | Scripted agents only (Phases 1–2), or `qwen2.5:0.5b` / `1.5b` for tests | Use a cloud API for any real LLM work |
| 8 GB | `llama3.2:3b` or `qwen2.5:3b-instruct` (Q4) | Close the browser and other apps while running |
| 16 GB | Same 3B models comfortably; a 7B (`qwen2.5:7b-instruct`) works but is slow | Use 7B only for the judge or for single agents |

### 14.3 Ollama settings for a low-spec laptop

```powershell
setx OLLAMA_NUM_PARALLEL 1
setx OLLAMA_MAX_LOADED_MODELS 1
setx OLLAMA_KEEP_ALIVE 30m
```
(Restart Ollama after `setx`.) In every request set `num_ctx: 2048` and `num_predict: 200`.

- Windows: **Settings → System → Power** → set the mode to *Best performance*, and keep the laptop plugged in.
- Keep it on a hard, ventilated surface. CPU inference heats the laptop up, and throttling can halve your speed.
- Measure your real speed: `ollama run llama3.2:3b --verbose` and read the `eval rate` (tokens per second) at the end. If it's under 2 tokens/s, drop to a 1.5B model.

### 14.4 Low-spec mode for the agent loop

- **One LLM call per agent per day.** The agent returns a single JSON plan and the engine executes it:
  ```json
  {"job": 3, "buy": [], "list": {"title": "Landing page", "price": 12}, "note": "save cash"}
  ```
- 6–8 agents per generation; prompts around 300 tokens plus a short memory summary.
- Use JSON/structured output so small models don't produce broken actions.
- Expect about 1.5–3 hours per generation (240 calls × 20–40 s). Run overnight.
- Hybrid option: keep agents local, and use a cloud API only for the judge and genome mutation (a handful of calls per generation).

---

## 15. Progress dashboard (web UI)

A local web page that shows what's happening and lets you approve actions, pause the world, and watch generations evolve. It runs on your laptop and reads the same SQLite database as the engine.

### 15.1 What it shows

| Panel | Content |
|---|---|
| **Header cards** | Current generation and day, alive / dead, total money, royalties paid, pending approvals, engine status (running / paused) |
| **Agents table** | ID, generation, parent, role, balance, status. Sorted by wealth |
| **Generations** | Survival rate and average wealth per generation (bars) |
| **Live events** | Latest 50 agent actions (tool, result) |
| **Approval queue** | Pending posts, purchases, and deployments with Approve / Reject buttons |
| **Controls** | Pause / Resume (kill switch) |

### 15.2 Extra tables the dashboard needs

Add these to the schema in Section 3:

```sql
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT DEFAULT CURRENT_TIMESTAMP,
  agent_id INTEGER, kind TEXT, payload_json TEXT,
  status TEXT DEFAULT 'pending'          -- pending | approved | rejected
);
INSERT OR IGNORE INTO meta(key,value) VALUES ('paused','0'),('generation','1'),('day','1');
```

The engine must:
- write `generation` and `day` to `meta` as it runs,
- check `meta.paused` before every agent step and stop when it is `1`,
- create a row in `approvals` for any gated action, and only execute it once `status='approved'`.

### 15.3 Backend: `dashboard/server.py`

```python
import json, sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "world.db"
app = FastAPI(title="Agent Economy Dashboard")

def q(sql, args=(), write=False):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        if write:
            con.commit()
            return []
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()

def meta(key, default="0"):
    r = q("SELECT value FROM meta WHERE key=?", (key,))
    return r[0]["value"] if r else default

@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/summary")
def summary():
    one = lambda sql: q(sql)[0]["n"]
    return {
        "generation": meta("generation", "1"),
        "day": meta("day", "1"),
        "paused": meta("paused") == "1",
        "alive": one("SELECT COUNT(*) n FROM agents WHERE status='alive'"),
        "dead": one("SELECT COUNT(*) n FROM agents WHERE status='dead'"),
        "money": one("""SELECT COALESCE(SUM(w.balance),0) n FROM wallets w
                        JOIN agents a ON a.wallet_id=w.id WHERE a.status='alive'"""),
        "royalties": one("SELECT COALESCE(SUM(amount),0) n FROM transactions WHERE reason LIKE 'royalty%'"),
        "pending": one("SELECT COUNT(*) n FROM approvals WHERE status='pending'"),
    }

@app.get("/api/agents")
def agents():
    rows = q("""SELECT a.id, a.parent_id, a.generation, a.status, a.genome_json, w.balance
                FROM agents a JOIN wallets w ON w.id=a.wallet_id
                ORDER BY w.balance DESC LIMIT 200""")
    for r in rows:
        try:
            r["role"] = json.loads(r.pop("genome_json") or "{}").get("role", "?")
        except Exception:
            r["role"] = "?"
    return rows

@app.get("/api/generations")
def generations():
    return q("""SELECT a.generation AS gen, COUNT(*) AS total,
                SUM(a.status='alive') AS alive, ROUND(AVG(w.balance),1) AS avg_balance
                FROM agents a JOIN wallets w ON w.id=a.wallet_id
                GROUP BY a.generation ORDER BY a.generation""")

@app.get("/api/events")
def events():
    return q("SELECT ts, agent_id, tool, result_json FROM events ORDER BY id DESC LIMIT 50")

@app.get("/api/approvals")
def approvals():
    return q("SELECT id, ts, agent_id, kind, payload_json FROM approvals WHERE status='pending' ORDER BY id")

@app.post("/api/approvals/{aid}/{decision}")
def decide(aid: int, decision: str):
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "bad decision")
    q("UPDATE approvals SET status=? WHERE id=? AND status='pending'", (decision, aid), write=True)
    return {"ok": True}

@app.post("/api/pause")
def pause():
    q("INSERT OR REPLACE INTO meta(key,value) VALUES('paused','1')", write=True)
    return {"paused": True}

@app.post("/api/resume")
def resume():
    q("INSERT OR REPLACE INTO meta(key,value) VALUES('paused','0')", write=True)
    return {"paused": False}
```

### 15.4 Frontend: `dashboard/static/index.html`

Agent output is untrusted text, so every value is escaped before it is shown.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Economy</title>
<style>
  :root{--bg:#0f1115;--card:#181b22;--tx:#e6e8ee;--mut:#8b93a7;--ok:#3ecf8e;--bad:#ef5b5b;--acc:#6aa6ff;--line:#262a33}
  @media (prefers-color-scheme: light){:root{--bg:#f5f6f8;--card:#fff;--tx:#1b1e25;--mut:#5d667a;--line:#e1e4ea}}
  *{box-sizing:border-box} body{margin:0;padding:16px;background:var(--bg);color:var(--tx);font:14px system-ui,sans-serif}
  h1{font-size:18px;margin:0 0 12px} h2{font-size:14px;margin:0 0 8px;color:var(--mut);font-weight:600}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:14px}
  .card,.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
  .card b{display:block;font-size:22px;margin-top:4px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}
  .scroll{overflow-x:auto;max-height:340px;overflow-y:auto}
  table{border-collapse:collapse;width:100%} th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--mut);font-weight:600} .ok{color:var(--ok)} .bad{color:var(--bad)}
  button{border:1px solid var(--line);background:var(--card);color:var(--tx);border-radius:6px;padding:5px 10px;cursor:pointer}
  button.primary{background:var(--acc);color:#fff;border-color:var(--acc)}
  .bar{height:10px;background:var(--line);border-radius:5px;overflow:hidden;min-width:80px} .bar i{display:block;height:100%;background:var(--ok)}
  .row{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
  .pre{white-space:pre-wrap;word-break:break-word;font:12px ui-monospace,monospace;color:var(--mut)}
</style>
</head>
<body>
<div class="row">
  <h1>Agent Economy <span id="status"></span></h1>
  <button id="toggle"></button>
</div>
<div class="cards" id="cards"></div>
<div class="grid">
  <div class="panel"><h2>Approval queue</h2><div class="scroll" id="approvals"></div></div>
  <div class="panel"><h2>Generations</h2><div class="scroll" id="gens"></div></div>
  <div class="panel"><h2>Agents</h2><div class="scroll" id="agents"></div></div>
  <div class="panel"><h2>Live events</h2><div class="scroll" id="events"></div></div>
</div>
<script>
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const get = u => fetch(u).then(r => r.json());
const post = u => fetch(u, {method:'POST'}).then(r => r.json());
let paused = false;

async function refresh() {
  try {
    const [s, a, g, e, p] = await Promise.all([
      get('/api/summary'), get('/api/agents'), get('/api/generations'),
      get('/api/events'), get('/api/approvals')]);
    paused = s.paused;
    $('#status').innerHTML = paused ? '<span class="bad">● paused</span>' : '<span class="ok">● running</span>';
    $('#toggle').textContent = paused ? 'Resume' : 'Pause all';
    $('#toggle').className = paused ? 'primary' : '';
    const card = (l, v) => `<div class="card">${esc(l)}<b>${esc(v)}</b></div>`;
    $('#cards').innerHTML = card('Generation', s.generation) + card('Day', s.day + ' / 30') +
      card('Alive', s.alive) + card('Dead', s.dead) + card('Total money', s.money) +
      card('Royalties paid', s.royalties) + card('Pending approvals', s.pending);

    $('#approvals').innerHTML = p.length ? '<table>' + p.map(x =>
      `<tr><td>#${esc(x.id)} agent ${esc(x.agent_id)} · <b>${esc(x.kind)}</b>
        <div class="pre">${esc(x.payload_json)}</div></td>
        <td><button class="primary" data-d="approved" data-id="${esc(x.id)}">Approve</button>
            <button data-d="rejected" data-id="${esc(x.id)}">Reject</button></td></tr>`).join('') + '</table>'
      : '<span class="pre">Nothing waiting.</span>';

    $('#gens').innerHTML = '<table><tr><th>Gen</th><th>Survival</th><th>Alive/Total</th><th>Avg $</th></tr>' +
      g.map(x => { const pct = x.total ? Math.round(100 * x.alive / x.total) : 0;
        return `<tr><td>${esc(x.gen)}</td><td><div class="bar"><i style="width:${pct}%"></i></div></td>
        <td>${esc(x.alive)}/${esc(x.total)}</td><td>${esc(x.avg_balance)}</td></tr>`; }).join('') + '</table>';

    $('#agents').innerHTML = '<table><tr><th>ID</th><th>Gen</th><th>Parent</th><th>Role</th><th>Balance</th><th>Status</th></tr>' +
      a.map(x => `<tr><td>${esc(x.id)}</td><td>${esc(x.generation)}</td><td>${esc(x.parent_id ?? '-')}</td>
        <td>${esc(x.role)}</td><td>${esc(x.balance)}</td>
        <td class="${x.status === 'alive' ? 'ok' : 'bad'}">${esc(x.status)}</td></tr>`).join('') + '</table>';

    $('#events').innerHTML = '<table>' + e.map(x =>
      `<tr><td>${esc((x.ts || '').slice(11, 19))}</td><td>A${esc(x.agent_id)}</td><td>${esc(x.tool)}</td>
       <td class="pre">${esc((x.result_json || '').slice(0, 120))}</td></tr>`).join('') + '</table>';
  } catch (err) { $('#status').textContent = '(waiting for engine/database…)'; }
}

document.addEventListener('click', async ev => {
  const b = ev.target.closest('button[data-id]');
  if (b) { await post(`/api/approvals/${b.dataset.id}/${b.dataset.d}`); refresh(); }
});
$('#toggle').onclick = async () => { await post(paused ? '/api/resume' : '/api/pause'); refresh(); };
refresh(); setInterval(refresh, 5000);
</script>
</body>
</html>
```

### 15.5 Run it

```powershell
pip install fastapi uvicorn
uvicorn dashboard.server:app --port 8000
```
Open **http://localhost:8000**. The page refreshes every 5 seconds.

- It listens on your laptop only by default. Don't expose it to the internet. If you want to check it from your phone on the same Wi-Fi, add `--host 0.0.0.0` and add a password first.
- Keep the engine and dashboard as two separate processes. The engine writes to SQLite, and the dashboard mostly reads. Turn on WAL mode in the engine (`PRAGMA journal_mode=WAL;`) so they don't block each other.

### 15.6 Dashboard roadmap

- **v1 (Phase 1):** header cards, agents table, generations, events (read-only)
- **v2 (Phase 3–4):** lineage tree, per-role income chart, marketplace listings and orders
- **v3 (Phase 5–6):** approval queue for posts and deployments, content previews, customer orders
- **v4 (Phase 7–8):** inventory, supplier costs, wallet reconciliation, alerts

---

## 16. Next steps

1. Run the CPU/RAM/disk check from Section 14.1 and note your results.
2. Build Phases 0 and 1 first (scripted agents, no LLM), with the dashboard v1 running from day one so you can see what's happening.
3. Pick the model tier from Section 14.2, measure your tokens per second, and only then switch agents to the LLM.
4. Keep every outward-facing action behind the approval queue until you trust the system.
5. Check legal and platform rules before each new real-world gateway.