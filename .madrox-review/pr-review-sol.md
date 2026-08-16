# Adversarial review: `feat/news-sentiment`

Reviewed the uncommitted working tree after reading `CLAUDE.md`. I traced the main and fallback execution paths, ran targeted Python reproductions, and ran the complete backend suite: **574 passed, 4 skipped, 2 xfailed**. That green suite does not cover several production seams below.

## 1. BLOCKING issues

### B1. Daily alpha interprets the newest-first price history backwards and ignores a refreshed live quote

**CONFIRMED** — `backend/analysis/context_builder.py:878-908`, `backend/analysis/context_builder.py:1029-1045`, `backend/analysis/alpha_engine.py:396-414`, `backend/analysis/alpha_engine.py:1216-1242`, `backend/analysis/alpha_engine.py:1313-1317`, `backend/analysis/alpha_engine.py:1085-1099`

`ContextBuilder` explicitly queries `PriceHistory` in descending date order, and a refresh prepends the live record at index 0. `_price_series()` preserves that order, but `_latest_close()` returns `closes[-1]` and `_pct_return()` treats the tail as the end of the period. A direct reproduction using closes `[120, 110, 100]` in the builder's real order returned a latest close of `100` and a one-bar return of `-9.09%`; the actual latest is `120` and the return is `+9.09%`. If a live refresh prepends `120`, alpha ignores it completely.

The failure propagates into daily scoring, portfolio overlays, and synthesized entry/stop levels. The daily alpha path also never checks `price_freshness`, so this is not rescued by the new freshness gate. This can invert momentum and create trade levels from the oldest bar in the context.

### B2. A one-tick refresh marks a symbol usable while leaving its chart and indicators stale or discontinuous

**CONFIRMED** — `backend/analysis/context_builder.py:1015-1057`, `backend/analysis/symbol_slice.py:315-350`, `backend/analysis/agents/technical_analyst.py:380-425`, `backend/analysis/agents/risk_analyst.py:394-451`

For stale database history, refresh prepends one partial live quote and changes freshness status to `refreshed`. The per-symbol partition therefore admits the symbol. Technical and risk analysts then compute recent OHLCV, support/resistance, and volatility over a sequence consisting of one current tick followed immediately by old bars, while separately supplied indicators remain those calculated from the stale database history. Because `refreshed` is treated as healthy, the prompt no longer displays the stale-data warning or the size of the gap.

Concrete scenario: the newest stored bar is April 30 and the run is June 19. A successful quote creates `[June 19 quote, April 30 bar, ...]`; the symbol passes the fail-closed gate, yet ATR/support/resistance/RSI are April-era or are calculated across a seven-week discontinuity. Optional rich TA may mask this when it succeeds, but its failure is deliberately non-fatal, so the stale splice is a supported production path. Refresh either needs enough bars to rebuild the analysis window/indicators, or the prompt must preserve the gap and prohibit history-derived levels.

### B3. The freshness contract fabricates quote dates and does not implement the claimed trading-day semantics

**CONFIRMED** — `backend/data/adapters/yahoo.py:242-252`, `backend/analysis/context_builder.py:932`, `backend/analysis/context_builder.py:1003`, `backend/analysis/context_builder.py:1031-1055`, `backend/analysis/context_builder.py:1081`, `backend/analysis/price_freshness.py:88-115`, `backend/analysis/price_freshness.py:146-167`

Yahoo exposes `regularMarketTime`, but refresh ignores it and stamps the price with `last_weekday(as_of)`. On Monday pre-market, on an exchange holiday, or when Yahoo returns a cached last trade, a Friday observation is relabelled Monday/current and declared fresh. UTC dates are also used rather than the exchange date, creating another boundary error around the New York session.

The “trading day” calculator only excludes weekends. A direct check from Thursday 2026-04-02 to Tuesday 2026-04-07 counts three days because Good Friday is treated as a session; the market had only two intervening sessions. At the two-day threshold, that turns an acceptable snapshot into stale and can drop every candidate during a holiday plus quote outage.

The validator also accepts non-finite, negative, zero, and future-dated observations as usable because it only rejects `None`. Direct probes produced `fresh` for `NaN`, a negative price, and a future date. The contract should use the source observation timestamp, an exchange calendar/timezone, and a finite positive-price/future-date check.

### B4. Honest `None` factor scores crash heatmap orchestration and force the stale-data legacy path

**CONFIRMED** — `backend/analysis/factor_model.py:99-104`, `backend/analysis/factor_model.py:116-162`, `backend/analysis/factor_model.py:397-439`, `backend/analysis/autonomous_engine.py:1117-1127`, `backend/analysis/autonomous_engine.py:2393-2406`, `backend/analysis/agents/opportunity_hunter.py:613-623`

The factor model correctly makes individual factors optional and accepts a stock at 50% coverage. Two rows with 5-day return, 20-day return, volume ratio, and volatility, but no RSI, produce exactly 50% coverage with `technical_score=None`. Formatting the resulting heatmap raises `TypeError: unsupported format string passed to NoneType.__format__` because the autonomous formatter applies `:.0f` unconditionally. `OpportunityHunter` repeats the same assumption for all six optional fields.

The outer orchestrator catches the heatmap exception and silently switches to the legacy path. That fallback does not apply the new freshness partition (B6), so the factor-coverage honesty change can directly route a run around the principal safety control.

### B5. Trade-level storage truncates prose mid-token, and the outcome parser mistakes indicator periods/timeframes for prices

**CONFIRMED** — `backend/models/deep_insight.py:122-138`, `backend/analysis/autonomous_engine.py:193-198`, `backend/analysis/autonomous_engine.py:1549-1552`, `backend/analysis/autonomous_engine.py:3062-3065`, `backend/analysis/autonomous_engine.py:4401-4404`, `backend/analysis/agents/synthesis_lead.py:263-265`, `backend/analysis/outcome_tracker.py:493-515`, `backend/analysis/outcome_tracker.py:552-563`

The live truncation is deterministic: `_level_text()` slices values to the ORM column length before both save paths. That is the root cause of values such as `"$370-385 (only on confirmation of SMA_50 support h"`; it is not merely a database-driver quirk. The prompts explicitly request commentary/timeframes inside the same fields, including examples such as `$830 (below 50-day SMA)`, while the schema allocates only 30–50 characters.

Downstream, `_parse_price_range()` extracts the first two numbers anywhere in the string and sorts them. Concrete failures:

- `$370 on confirmation of SMA_50` becomes `(50, 370)`, so the entry midpoint is `$210` and the 15% sanity gate rejects a valid trade near `$380`.
- `$350 below SMA_50` becomes `(50, 350)`; for a bullish thesis, the stop check uses `$50`, not `$350`.
- A bearish target such as `$180 within 3 months` becomes `(3, 180)`, so the target is not considered hit until price reaches `$3`.

This corrupts both admission and grading, precisely the feedback loop the branch is intended to repair. Store numeric level columns separately from prose/conditions, or require and validate a structured response.

### B6. The advertised fail-closed behavior is inconsistent, bypassable, and can silently report success with zero stored insights

**CONFIRMED** — `backend/analysis/autonomous_engine.py:1350-1390`, `backend/analysis/autonomous_engine.py:1600-1617`, `backend/analysis/autonomous_engine.py:2956-2965`, `backend/analysis/autonomous_engine.py:3127-3144`, `backend/analysis/autonomous_engine.py:3364-3445`, `backend/analysis/autonomous_engine.py:3498-3517`, `backend/analysis/autonomous_engine.py:4467-4484`

There are three incompatible behaviors:

1. The heatmap deep-dive path drops symbols whose price cannot be verified.
2. The legacy fallback builds symbol contexts but never calls the freshness partition, so stale/missing-price symbols are analyzed anyway.
3. The store gate returns `True` for a missing symbol, missing entry, or unparseable entry such as `N/A`/`at market`, despite its fail-closed description. Only parseable numeric prose is actually verified.

Store rejections only increment a local counter and log; they do not populate `result.errors`. Synthesis summaries use the pre-gate `len(insights_data)`, so the phase can say “Generated N” even when `result.insights` is empty. Realistic zero-output states include a normal price-ETL lag combined with a temporary Yahoo outage (all heatmap candidates dropped) and a synthesis batch whose numeric entries all fail the gate. The run should expose a degraded/data-outage state and accurate stored counts, not complete with a misleading success summary.

### B7. Single-symbol yfinance downloads use the wrong column-shape assumption, causing invisible coverage loss

**CONFIRMED** — `backend/analysis/agents/heatmap_fetcher.py:410-437`, `backend/analysis/agents/heatmap_fetcher.py:511-535`, `backend/analysis/agents/heatmap_fetcher.py:629-685`

The installed yfinance version defaults to `multi_level_index=True`. `_extract_frames()` assumes any one-symbol response is flat and stores the raw frame. A reproduction using the dependency's ticker/field MultiIndex shape recorded the symbol as downloaded, then `_compute_metrics()` failed on `df["Close"]` and returned `None`. All individual retries are one-symbol downloads, and a one-item final batch has the same problem.

This is particularly misleading because the download manifest counts the frame in `data`, so batch coverage can look healthy while the stock vanishes from computed metrics. The test fake returns flat columns specifically for a single symbol and therefore cannot reveal the installed dependency mismatch.

### B8. Fundamental placeholders still become scored evidence in daily alpha

**CONFIRMED** — `backend/data/adapters/yahoo.py:381-459`, `backend/analysis/alpha_engine.py:506-688`, `backend/analysis/alpha_engine.py:969-1035`

Any nonempty Yahoo `info` mapping emits a nonempty fundamental record even if all extracted fields are `None`. Daily alpha uses `bool(fundamental_data)` as its usability test, enabling the fundamental, valuation, catalyst, and liquidity factors. Their absent inputs then resolve to neutral/default scores.

A direct comparison showed an empty fundamental mapping enabling three real factor families, while an all-`None` yfinance-shaped mapping enabled seven and changed the score/completeness despite adding zero observations. `ContextBuilder` happens to suppress all-`None` fundamentals in prose, but the scoring consumer does not. This violates the new evidence-usability rule and preserves exactly the “unavailable becomes neutral evidence” defect for a major pipeline.

### B9. Statistical features use the oldest 300 rows, then seasonality always raises and is silently swallowed

**CONFIRMED** — `backend/analysis/statistical_calculator.py:153-180`, `backend/analysis/statistical_calculator.py:510-526`, `backend/analysis/statistical_calculator.py:551-552`, `backend/analysis/statistical_calculator.py:791-797`, `backend/analysis/autonomous_engine.py:3225-3234`, `backend/analysis/autonomous_engine.py:4561-4570`

`pd.to_datetime(dates[1:])` produces a `DatetimeIndex`; comparisons on `.dayofweek` and `.month` produce NumPy arrays. Calling `.values` on the day-of-week mask raises the observed `AttributeError: 'numpy.ndarray' object has no attribute 'values'`. The broad per-symbol exception swallows it and orchestration still logs that statistical features were computed for every symbol. Momentum/mean-reversion/volatility rows created before the exception may survive, but seasonality contributes nothing.

More seriously, the database query orders ascending and then applies `LIMIT 300`. For symbols with more than 300 bars, every surviving statistical family is calculated from the **oldest** 300 observations and stamped as current. This is silent stale evidence, not just a missing optional feature. Query the latest 300 descending and reverse them for calculation, and isolate/repair seasonality rather than discarding the remainder under a broad exception.

## 2. NON-BLOCKING issues, ranked

### N1. Sector ETF and breadth evidence overstate sparse coverage

**CONFIRMED (high)** — `backend/analysis/agents/heatmap_fetcher.py:351-381`, `backend/analysis/agents/heatmap_fetcher.py:778-785`

Any nonempty ETF metrics use `0` for missing 5-day and 20-day returns, so a two-bar ETF can be presented as measured `+0.00%` performance. Breadth becomes valid at three stocks regardless of universe size or metric completeness; 3/70 names can therefore be labelled valid breadth. Preserve missing values and require a proportionate coverage threshold.

### N2. `floatShares` alone produces a false low-short-interest signal

**CONFIRMED (high)** — `backend/data/adapters/short_interest.py:36-39`, `backend/data/adapters/short_interest.py:151-159`, `backend/data/adapters/short_interest.py:179-207`

`floatShares` counts as a short-interest field. A direct probe with only `{"floatShares": 1_000_000}` returned `available=True`, partial coverage, squeeze score 0, and `low_short_interest`, although no short-position observation existed. Float size is a denominator/context field, not evidence that short interest is low.

### N3. The new `Evidence` contract is mostly a test-only type and cannot distinguish outages from absent coverage

**CONFIRMED (medium-high)** — `backend/data/adapters/evidence.py:49-111`, `backend/data/adapters/analyst_revisions.py:179-201`, `backend/data/adapters/short_interest.py:145-159`

Runtime adapters emit matching dictionaries but do not instantiate `Evidence`; `observed_at` is generally absent, making freshly fetched old source data look current. Adapter exceptions are converted to `unavailable/no_coverage` rather than `error`, so consumers cannot tell a legitimate empty source from an outage. Also, `Evidence.__post_init__` clamps `NaN` coverage to `1.0` because of Python `min`/`max` behavior. Validate finite coverage and preserve source observation/error semantics.

### N4. `ContextBuilder`'s advertised five-minute cache cannot hit

**CONFIRMED (medium)** — `backend/analysis/context_builder.py:193`, `backend/analysis/context_builder.py:291-299`, `backend/analysis/context_builder.py:391-392`, `backend/analysis/context_builder.py:2288-2297`

The cache-hit condition requires `_last_cache_key == cache_key`, but a completed build updates only the context and timestamp; `_last_cache_key` is never assigned after initialization. Every `build_context()` call rebuilds and refetches. This limits the current shared-mutation risk, but contradicts the documented behavior relied on by `symbol_slice` and can amplify adapter load/rate limits. `get_cached_context()` also returns the last context without validating the caller's key.

### N5. Dynamic-universe categories create duplicate heatmap rows and unstable category attribution

**CONFIRMED (medium)** — `backend/analysis/agents/heatmap_fetcher.py:241-245`, `backend/analysis/agents/heatmap_fetcher.py:273-293`, `backend/analysis/autonomous_engine.py:2855`

Symbols are deduplicated for download but not when entries are built per category. Because sector leaders can also be innovation/mover candidates, the prompt may count and rank the same ticker multiple times. Later dict construction silently keeps the last category, so category attribution depends on list order.

### N6. Refreshed prices are logged as not fresh

**CONFIRMED (low)** — `backend/analysis/context_builder.py:980`

The warning count treats every status other than literal `fresh` as unhealthy, including successfully `refreshed` records. This can generate fake ETL-health warnings and obscure actual stale/unavailable counts.

### N7. Market-session labelling uses fixed UTC-5 and opens at 09:00

**CONFIRMED (low)** — `backend/analysis/agents/heatmap_fetcher.py:723-742`, `backend/analysis/context_builder.py:1490-1512`

The code ignores US daylight saving time and treats 09:00 rather than 09:30 Eastern as open. Freshness/status prose is wrong for part of the year and for the first half hour of the pre-market/open boundary.

## 3. TEST QUALITY findings

The suite is useful regression coverage for the happy-path mechanics, but several tests encode the implementation's assumptions rather than production contracts.

- `backend/tests/test_price_freshness.py::test_stale_db_bars_are_refreshed_from_live_adapter` and `backend/tests/test_benchmark_freshness.py::test_stale_benchmark_is_refreshed_to_a_live_quote` use fake quotes with no source timestamp and assert that the quote is stamped with the current weekday. They positively lock in B3's fabricated observation date. There are no holiday, pre-market, exchange-timezone, future-date, NaN, or non-positive-price cases.
- The batch/single-symbol tests in `backend/tests/test_heatmap_fetcher.py` use a `FakeYF` that returns flat columns for one symbol. That does not model the installed yfinance default, so B7 remains invisible. There is also no partial-ETF-metric or three-of-a-large-universe breadth case for N1.
- `backend/tests/test_factor_model.py::TestFactorCoverage::test_unmeasured_factors_are_none_not_neutral` correctly checks the model object but never passes it to autonomous heatmap formatting or `OpportunityHunter`. The only missing-factor rendering assertion is for a separate report formatter. Thus the producer is tested while both crashing consumers are not.
- `backend/tests/test_trade_levels_gate.py::test_insight_without_entry_zone_is_not_gated` and `::test_non_numeric_entry_zone_is_not_gated` explicitly bless fail-open behavior that conflicts with the documented verification gate. There are no prose examples containing `SMA_50`, percentages, or timeframes, and no persistence assertion for truncation.
- `backend/tests/test_context_evidence_gating.py::test_fundamentals_without_an_evidence_contract_are_unaffected` intentionally exempts fundamentals. `backend/tests/test_alpha_engine_evidence.py` always supplies meaningful fundamental values. Together they miss B8's all-`None` runtime shape.
- `backend/tests/test_evidence_contract.py` constructs `Evidence` directly, including `observed_at`, but production adapters do not. The adapter-contract tests largely exercise empty returns and do not require correct error classification, observation timestamps, or finite coverage.
- Short-interest tests cover a true placeholder and real short fields, but not the `floatShares`-only payload that produces N2.
- There is no integration test for `run_daily_factor_scoring()` with `ContextBuilder`'s actual newest-first ordering or a prepended refresh; no test for the legacy path's freshness bypass; and no test for a run where every symbol/insight is dropped.
- There are no tests for `StatisticalCalculator` seasonality or for selecting the most recent 300 database rows. The broad exception makes a superficial “method completed” test insufficient.

The 574 passing tests therefore establish that the individual phase implementations match their local mocks. They do not establish that the rebuilt evidence layer is correct end-to-end.

## 4. WHAT IS GOOD

- The per-symbol slice fixes the headline identical-prompt defect: it creates a symbol-specific outer context, performs case-normalized selection, and labels the target explicitly. Current analyst formatters appear read-only, and copied freshness records avoid the obvious concurrent mutation hazard; I did not find a confirmed asyncio race in the present consumers.
- News entity validation is materially better: exact ticker/cashtag/name/exchange matching avoids the CAT/RCAT/ASTE substring failure and preserves the difference between quiet coverage and adapter failure.
- Options aggregation now uses the full chain and handles missing/NaN data more honestly.
- The core factor model's move from fake 50s to `None`, coverage accounting, and weight renormalization is directionally correct. The failures are in downstream consumers, not that core decision.
- Price provenance, explicit usability states, benchmark batching, persisted synthesis levels, and a live-price sanity check are all the right controls to add.

The change is **not sound as a whole yet**. Several of its strongest local fixes are bypassed or misinterpreted at integration boundaries.

## 5. VERDICT

**REQUEST CHANGES**

The deciding issues are not cosmetic: daily alpha reads price history backwards; refreshed prices are falsely dated and leave the analytical window stale; legitimate missing factors crash the new path into an ungated fallback; prose trade levels are truncated and numerically misparsed; fundamentals still convert absence into neutral evidence; and statistical features are calculated from the oldest history while errors are reported as success. Any one of B1, B3/B2, B4/B6, B5, or B9 can materially corrupt recommendations or their grading. Fix those cross-pipeline contracts and add integration tests using actual dependency/data shapes before approval.
