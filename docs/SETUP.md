# Setup

Clone to a running console in about fifteen minutes, most of it a model
download. Instructions for **macOS/Linux** and **Windows** side by side.

If any step doesn't work as written, that's a bug in this document — tell
Shashank rather than working around it.

---

## What you need first

| | |
|---|---|
| **Python 3.11+** | 3.12 recommended. `python3 --version` / `python --version` |
| **Git** | |
| **The database URL** | Ask Shashank. It is a secret and is **not** in the repo. |
| **Ollama** *(optional)* | Only for the local model. Everything else runs without it. |

---

## 1. Clone and install

**macOS / Linux**
```bash
git clone https://github.com/shashank-sk17/dcortex-crew-advisor.git
cd dcortex-crew-advisor
git checkout feat/shashank/dev-console

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/shashank-sk17/dcortex-crew-advisor.git
cd dcortex-crew-advisor
git checkout feat/shashank/dev-console

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell blocks the activate script, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window
> and try again. On **Command Prompt** use `.venv\Scripts\activate.bat`.

**Check it worked** — this should print `PASS` on both platforms:

```bash
python crew-ops-advisor-dataset/validate.py
```

That confirms the vendored dataset is intact. Never edit anything under
`crew-ops-advisor-dataset/` — it is dCortex's data and `validate.py` is how we
know it stayed that way.

---

## 2. Add the database URL

Create a file called `.env` in the repo root with one line:

```
DATABASE_URL=postgresql://...paste the URL Shashank gives you...
```

**macOS / Linux**
```bash
printf 'DATABASE_URL=%s\n' 'PASTE_URL_HERE' > .env
chmod 600 .env
```

**Windows (PowerShell)**
```powershell
'DATABASE_URL=PASTE_URL_HERE' | Out-File -Encoding ascii .env
```

`.env` is gitignored. **Do not commit it, paste it into a ticket, or put it in
a screenshot.** If it leaks, tell Shashank so it can be rotated.

**Check it worked:**
```bash
python -c "from core.port import CoreToolPort; print(CoreToolPort().world.crew['C-1042'])"
```

You should see a `CrewSnapshot` for A. Nair. If you see
`no DATABASE_URL in the environment or .env`, the file is in the wrong place or
misspelled.

---

## 3. Run the tests

```bash
pytest -q
```

**334 passing.** Roughly twenty of those talk to the database and skip
automatically if `DATABASE_URL` is missing, so a clean run without the URL
shows skips rather than failures.

---

## 4. Start the console

```bash
python -m devui.server
```

Open **http://localhost:8420**.

That runs with no model and no database — enough to see the interface. To pick
backends, set environment variables first:

**macOS / Linux**
```bash
AGENT_DATA=core AGENT_LLM=ollama python -m devui.server
```

**Windows (PowerShell)**
```powershell
$env:AGENT_DATA="core"; $env:AGENT_LLM="ollama"; python -m devui.server
```

**Windows (Command Prompt)**
```cmd
set AGENT_DATA=core && set AGENT_LLM=ollama && python -m devui.server
```

### The backends

| `AGENT_DATA` | What answers your question |
|---|---|
| `json` *(default)* | Vendored JSON files. Tier 1 only. No database needed. |
| `postgres` | Real reads from Neon. Tier 1 only — no rules engine. |
| `fixtures` | JSON lookups + dCortex's answer keys for tiers 2 and 3. Correct data, but replayed for five pairings only. |
| **`core`** | **The rules engine. Everything computed from the database, any pairing.** |

| `AGENT_LLM` | |
|---|---|
| `placeholder` *(default)* | No model. Answers come from templates — terse but correct. |
| **`anthropic`** | **Recommended. `claude-opus-5`. Needs a key.** |
| `groq` | Hosted, free tier, rate limited. |
| `ollama` | Local. Needs step 5 and a 5 GB download. |

### Anthropic (recommended)

Ask Shashank for the key and add it to the same `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Then:

```bash
AGENT_DATA=core AGENT_LLM=anthropic python -m devui.server      # macOS/Linux
```
```powershell
$env:AGENT_DATA="core"; $env:AGENT_LLM="anthropic"; python -m devui.server
```

Model is `claude-opus-5`; override with `ANTHROPIC_MODEL`. Around two seconds
for a lookup, longer for tier 3 where several model calls are needed.

The system prompt and tool schemas are byte-identical on every call, so they
are cached — about **80% of input tokens come from cache**, which is what makes
a multi-call tool loop affordable.

### Groq (alternative)

`GROQ_API_KEY=gsk_...`, then `AGENT_LLM=groq`. Model `qwen/qwen3.6-27b`, 5/5 on
tool calls. **The free tier allows 7,000 input tokens per minute** and a tier-2
question runs about 1,400, so expect throttling on a busy session — the client
retries using the delay Groq reports, which is why an answer occasionally takes
twenty seconds.

The status bar at the top of the console always names which is live, so you
never have to guess what produced an answer.

---

## 5. The local model *(optional)*

Only needed for `AGENT_LLM=ollama`. Skip this if you are using Groq. Everything works without it — the
templates produce correct answers, just plainer ones.

**macOS**
```bash
brew install ollama        # or download from https://ollama.com
ollama serve &             # leave running
ollama pull qwen3:8b       # ~5.2 GB
```

**Windows** — download the installer from <https://ollama.com/download>. It
runs as a background service, so no `ollama serve` needed.
```powershell
ollama pull qwen3:8b
```

**Check it worked:**
```bash
ollama list
```

`qwen3:8b` should be listed. Expect **10–30 seconds per question** on a laptop.

> **Why qwen3 and not Llama?** Measured on our tool schemas at temperature 0:
> qwen3:8b gets 4/4 tool calls, llama3.1:8b 4/4, llama3.2 2/4, and llama3 0/4
> because the original Llama 3 has no tool support at all. Reasoning mode is
> off deliberately — with it on, qwen3 skips the tool and answers from the
> prompt instead, which defeats the whole design. See `agent/README.md`.

---

## 6. Try it

Type these into the console, or click any of the 38 gold questions in the left
rail.

| Question | What it shows |
|---|---|
| `Who is on reserve at BLR on 2026-09-15?` | Tier 1, real data, every claim traced |
| `What does RULE-DUTY-02 say?` | Rule lookup with citations |
| `Captain of P-2291 is not available on 2026-09-15` | **The main one** — recommendation, alternatives, cancel contrast, candidate funnel |
| `If C-2087 covers P-2291, does any rule breach?` | Rule-by-rule verdict with the numbers |
| `Both A320 captains are sick at 00:30Z on 18 Sep. Give the optimal joint plan.` | Joint assignment, ₹42,500, 20 equal-cost ties |

Then keep the thread going — the console holds a conversation:

| Follow-up | |
|---|---|
| `why not C-2087?` | the exclusion reason, no new tool call |
| `what about C-2210?` | legal, ranked #5, ₹41,200 and a 3h delay |
| `go with C-3310` | recorded as the decision |

And try getting it wrong on purpose. `C-1024 is sick` (a transposed digit),
`FO C-2087` (the wrong rank — which is what dCortex's own brief says), or
`move C-2087 onto DX412` (a flight that runs on three days). Each should ask
you a question rather than guess, and the next message answers it.

`#q=...` in the URL re-runs a question, so you can paste a failing case into
Slack and someone else reproduces it exactly.

---

## Troubleshooting

**`port 8420 is already in use`** — another console is running.

```bash
lsof -ti:8420 | xargs kill          # macOS / Linux
```
```powershell
Get-NetTCPConnection -LocalPort 8420 | Select -Expand OwningProcess | Stop-Process
```

**`ModuleNotFoundError: No module named 'agent'`** — run commands from the repo
root with the virtualenv active, not from inside a subfolder.

**`cannot reach Ollama at http://localhost:11434`** — the daemon isn't running.
`ollama serve` on macOS; check the system tray on Windows.

**`no DATABASE_URL`** — `.env` is missing, misnamed, or in the wrong directory.
It belongs beside `README.md`.

**Console loads but every answer says "Cannot answer this yet"** — you're on a
backend without the rules engine. Restart with `AGENT_DATA=core`.

**Page looks stale after an update** — hard-reload the browser
(Cmd+Shift+R / Ctrl+Shift+R). Python changes need a server restart; page
changes only need the reload.

---

## Where to read next

1. [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) — what the system actually does and why
2. [`FRONTEND.md`](FRONTEND.md) — **if you are building the UI, start here**
3. [`../agent/README.md`](../agent/README.md) — the advisor layer in detail
4. [`RULES.md`](RULES.md) — the seven rules and the traps in them
