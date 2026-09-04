# SETUP.md

Clone → running in under ten minutes. If it takes longer than that, open a `blocker` issue rather than grinding on it alone.

---

## Everyone

```bash
git clone git@github.com:shashank-sk17/dcortex-crew-advisor.git
cd dcortex-crew-advisor
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 crew-ops-advisor-dataset/validate.py   # must print PASS
```

**Never edit anything under `crew-ops-advisor-dataset/`.** It's vendored and unmodified — `validate.py` is our canary that it stayed that way.

Then read, in order: [`../README.md`](../README.md) → [`API_CONTRACT.md`](API_CONTRACT.md) → [`RULES.md`](RULES.md) → your section in README §8.

---

## Kashifa — World & Legality

```bash
pytest core/ -v                    # your test suite
pytest core/test_lex.py -k duty02  # one rule at a time
```

Your day-one deliverable is `core/loader.py` + `core/world.py`, because all three of us are blocked on it. It's the least interesting thing you'll build this week — ship it fast and move to LEX.

**Read [`RULES.md`](RULES.md) before writing LEX.** The two traps in there are where silent wrong answers come from. Your canary is Q02: `duty_hours_7d = 20.93`, `headroom_hours = 39.07`.

---

## Gayathri — Reasoning & Evals

```bash
python evals/harness.py                    # full scorecard
python evals/harness.py --tier 1           # one tier
python evals/harness.py --question Q17     # one question, verbose diff
```

Start with the harness — it's fully self-contained, so you can build and land it before anyone else's code exists, and it's how the whole team knows where we stand.

Then RIPPLE, starting from Q17 (`day2_also_at_risk`, `passengers_day1: 486`). That answer key tells you exactly what a correct cascade produces; work outward from it. Every module you own has a scenario that scores it — use them as the spec.

---

## Shashank — Advisor Agent

```bash
export ANTHROPIC_API_KEY=...              # .env, never committed
python -m agent.cli "Who is on reserve at BLR on 2026-09-15?"
python -m agent.cli --tier 2 --scenario S2
```

Freeze `API_CONTRACT.md` first — Kiran and the harness are both waiting on the shapes, not the implementation.

---

## Kiran — Ops Console

```bash
cd frontend
npm install
npm start                                  # http://localhost:4200

# in another shell — mock API, no Python core needed
python -m api.mock                         # http://localhost:5000
```

The mock server serves `evals/fixtures/`, which are lifted from the answer keys — **so what you build against mocks is what ships.** Point at the real API by changing one base URL in the environment file once the core lands.

---

## Common

```bash
make test        # pytest + harness
make demo        # boot everything, seed scenarios, open the console
make lint
```

### Env vars
| Var | Who | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Shashank | `.env`, gitignored. Never commit. |
| `API_BASE` | Kiran | defaults to `http://localhost:5000` |

---

## Working rhythm

- Branch `feat/<owner>/<slug>`, small PRs, squash merge.
- **`main` is always demoable.** If you break it, fixing it is your top priority.
- Status pulse in [`../PROGRESS.md`](../PROGRESS.md) every four hours — four lines, one minute.
- Stuck? Open a `blocker` issue immediately. Don't lose two hours being polite about it.
