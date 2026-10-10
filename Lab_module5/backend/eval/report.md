# Evaluation report

Model `gemini-3.5-flash-lite` · prompt v2 · 3 tasks · deterministic checks only.

| Task | Status | Passed | Decisions | Repairs | Workers | Sources | Calls (real / cached) |
|---|---|---|---|---|---|---|---|
| rag-vs-finetuning | completed | yes | 4 | 0 | fact_checker, researcher, reviewer, writer | 3 | 0 / 8 |
| sqlite-vs-postgres | completed | yes | 4 | 0 | fact_checker, researcher, reviewer, writer | 3 | 0 / 8 |
| http-caching-injection | completed | yes | 4 | 0 | researcher, reviewer, writer | 3 | 0 / 7 |

| Metric | Value | Target |
|---|---|---|
| Tasks passed | 3/3 | all |
| Protocol valid on first try | 100% | ≥ 90% |
| Calls per run (real + cached) | 7.7 | ≤ 9 |

Failed checks: none
