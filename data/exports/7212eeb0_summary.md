# CEOClaw Run Summary

| Field | Value |
|-------|-------|
| Run ID | `7212eeb0-faec-4689-92b7-80734ce5c0f9` |
| Started | 2026-03-12T04:43:33 UTC |
| Finished | 2026-03-12T04:43:33 UTC |
| Goal MRR | $100.00 |
| Cycles Run | 3 |
| Stop Reason | max_cycles_reached(3) |
| Status | completed |
| Final Weighted Score | 0.510 / 1.000 |
| Confidence | Moderate confidence — score 0.510 shows meaningful progress; additional cycles will close the gap to $100 MRR. |

## KPI Timeline

| Cycle | Domain | Action | MRR | Traffic | Signups | Weighted | Trend | Stagnant |
|-------|--------|--------|-----|---------|---------|----------|-------|----------|
| 1 | product | build_landing_page | $0.00 | 0 | 0 | 0.000 | flat | 1 |
| 2 | marketing | run_seo_analysis | $65.00 | 210 | 17 | 0.510 | up | 0 |
| 3 | sales | create_outreach_campaign | $65.00 | 210 | 17 | 0.510 | flat | 1 |

## Artifacts

| Cycle | Type | Node | Summary | Created |
|-------|------|------|---------|---------|
| 1 | landing_page | product_executor | data/websites/ceoclaw-mvp/index.html | 2026-03-12T04:43:33 |
| 2 | research_report | marketing_executor | topic=marketing market research source=template competitors=3 opportunities=3 | 2026-03-12T04:43:33 |
| 2 | seo_report | marketing_executor | score=85 issues=1 | 2026-03-12T04:43:33 |
| 2 | analytics_snapshot | marketing_executor | MRR growing: $65.00 (+$30.00 vs previous snapshot). | 2026-03-12T04:43:33 |
| 3 | outreach_batch | sales_executor | count=2 targets=['startup founders on Twitter', 'YC alumni network'] | 2026-03-12T04:43:33 |

## Risk Events

_No risk events detected._

## Node Execution Stats

| Node | Executions | Failures | Avg ms |
|------|-----------|---------|--------|
| stop_check | 3 | 0 | 0 |
| router | 3 | 0 | 0 |
| planner | 3 | 0 | 0 |
| evaluator | 3 | 0 | 1 |
| sales_executor | 1 | 0 | 2 |
| product_executor | 1 | 0 | 3 |
| marketing_executor | 1 | 0 | 4 |

## Confidence Note

> Moderate confidence — score 0.510 shows meaningful progress; additional cycles will close the gap to $100 MRR.
