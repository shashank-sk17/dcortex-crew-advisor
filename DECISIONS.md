# DECISIONS

Append-only. One line each, newest at the bottom. If you reverse a decision, add a new row — don't edit the old one.

Format: `date · decision · why`

---

| # | Date | Decision | Why |
|---|---|---|---|
| 1 | 2026-09-04 | **No database.** In-memory `World` built from the 12 JSON files. | Dataset is < 700 KB (150 crew, 147 flights, 39 pairings). Postgres/Neo4j/Mongo/Celery cost the better part of a day and buy nothing at this scale. |
| 2 | 2026-09-04 | **The LLM never calculates.** Every number comes from a deterministic tool; a verifier gate rejects untraced claims. | A controller cannot act on a number that might have been invented. This is the trust boundary the whole architecture is built around. |
| 3 | 2026-09-04 | **Freeze `docs/API_CONTRACT.md` before implementation.** Fixtures derived from the answer keys. | Lets four people build in parallel. Because the fixtures *are* the correct answers, the mock→real swap is a no-op. |
| 4 | 2026-09-04 | **Typed answer object per tier; prose rendered from it.** | Answer keys are structured JSON, so the harness can score us exactly. Prose-first would make that impossible. |
| 5 | 2026-09-04 | **JUDGE's default config must reproduce the answer keys exactly.** Policy sliders layer on top. | Ranking is cost-deterministic `(legal, cost_inr, delay_hours)` off a fixed rate card. This is correctness, not preference. |
| 6 | 2026-09-04 | **`JOINT` is a first-class module.** | S6 is a joint optimisation (`total_cost_inr: 42500`). Greedy provably fails it — both aircraft grab the same cheapest reserve. |
| 7 | 2026-09-04 | **Describe JUDGE as *provably optimal*, not *learned*.** Log preference pairs for future learning. | We don't have a trained ranker and shouldn't claim one. The exact-optimality claim is stronger and survives questioning. |
| 8 | 2026-09-04 | **Held-out scenarios (`internal/`) are locked.** Run once at T+21 as an honest self-check. | Tuning against the judging set is overfitting. A defensible 96% beats an unexplainable 100%. |
| 9 | 2026-09-04 | **Out of scope: passenger rebooking, disruption-risk prediction.** | Pax impact is a RIPPLE *output*, not a subsystem. The dataset README is explicit that risk scores are provided input — teams do not build prediction. |
| 10 | 2026-09-04 | **`Option` keeps answer-key field names verbatim.** Additive fields only. | The harness compares against them directly. Renaming breaks scoring silently. |
