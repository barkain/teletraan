# Adversarial Review: `feat/news-sentiment`

Reviewed uncommitted working-tree changes in `/Users/nadavbarkai/dev/teletraan`. I read `CLAUDE.md`, inspected `git status --porcelain`, reviewed `git diff` plus the untracked new modules/tests, traced the relevant execution paths, and ran `cd backend && uv run pytest -q`: `574 passed, 4 skipped, 2 xfailed`.

## BLOCKING Issues

### 1. CONFIRMED - LLM trading-level prose is truncated before storage, and some prose bypasses the sanity gate

Files:
- `backend/analysis/autonomous_engine.py:193-198`
- `backend/analysis/autonomous_engine.py:2960-2965`
- `backend/analysis/autonomous_engine.py:3062-3065`
- `backend/analysis/autonomous_engine.py:4401-4404`
- `backend/models/deep_insight.py:122-138`
- `backend/analysis/agents/synthesis_lead.py:250-266`
- `backend/analysis/agents/synthesis_lead.py:1549-1552`

Failure scenario:
- Input from synthesis: `entry_zone="$370-385 (only on confirmation of SMA_50 support holding)"`, `stop_loss="$350 (below SMA_50 support and prior pivot)"`.
- `_level_text(..., 50)` slices the strings before insert, yielding values like `"$370-385 (only on confirmation of SMA_50 support h"`.
- The DB model still uses `String(50)`/`String(30)` for fields that the synthesis prompt explicitly encourages to contain timeframe or explanatory parentheticals.
- The entry gate parses only `entry_zone`, and if `_parse_price_range()` returns `None`, it returns `True` at `autonomous_engine.py:2960-2965`. Qualitative or malformed prose such as `"only after reclaiming SMA_50 support"` is stored without verification. `target_price` and `stop_loss` are not verified at all.

Root cause:
- The same short string column is being used for both a machine-verifiable numeric level and human explanatory prose.
- The application code forcibly truncates to fit those short columns before storage. This is not just a database truncation issue.

Impact:
- The live truncation report is reproducible from the current code path.
- Outcome tracking and reports receive corrupted trade-level text.
- The new store-time gate does not guarantee that stored levels are parseable, complete, or non-corrupted.

### 2. CONFIRMED - statistical seasonality feature computation fails for ordinary DataFrames and is swallowed

Files:
- `backend/analysis/statistical_calculator.py:173-180`
- `backend/analysis/statistical_calculator.py:520-526`
- `backend/analysis/statistical_calculator.py:550-552`
- `backend/analysis/autonomous_engine.py:3225-3236`
- `backend/analysis/autonomous_engine.py:4561-4568`

Failure scenario:
- Input: a normal `prices_df` with a `date` column and 80 rows of OHLCV data.
- `_compute_seasonality_features()` does `date_series = pd.to_datetime(dates[1:])`; that is a `DatetimeIndex`.
- `date_series.dayofweek == current_dow` returns a `numpy.ndarray`, not a pandas object.
- `dow_mask.values` at `statistical_calculator.py:526` raises `AttributeError: 'numpy.ndarray' object has no attribute 'values'`. `month_mask.values` at `statistical_calculator.py:552` has the same bug.
- The per-symbol broad `except Exception` at `statistical_calculator.py:179-180` logs and continues, so callers do not fail the run.

Read-only probe result:
- Reproduced exactly with an 80-row DataFrame: `AttributeError 'numpy.ndarray' object has no attribute 'values'`.

Impact:
- The seasonality block contributes nothing for normal symbols.
- Momentum/mean-reversion/volatility features already appended before the exception may still be saved, so the failure mode is partial and misleading rather than a clean outage.
- The autonomous engine logs success after `compute_all_features()` returns, even though a core feature group failed for most symbols.

### 3. CONFIRMED - all-None Yahoo fundamentals still count as usable evidence and reintroduce neutral placeholder scoring

Files:
- `backend/data/adapters/yahoo.py:404-439`
- `backend/analysis/alpha_engine.py:597`
- `backend/analysis/alpha_engine.py:642-643`
- `backend/analysis/alpha_engine.py:673-686`
- `backend/analysis/alpha_engine.py:969-1035`

Failure scenario:
- yfinance returns a non-empty `ticker.info` payload, but the scoring fields are unavailable or all `None`.
- `YahooAdapter.get_fundamental_data()` returns a non-empty dict with many keys and `None` values.
- `_score_with_evidence()` sets `fundamentals_usable = bool(fundamental_data)` at `alpha_engine.py:969`.
- `_score_fundamentals()` supplies neutral/default values: fundamental score `50`, valuation component `50`, catalyst default `45`, liquidity default `50`.
- Because `fundamentals_usable` is true, `fundamental`, `valuation`, `catalyst`, and `liquidity` are marked usable and included in the composite weights at `alpha_engine.py:1027-1035`.

Read-only probe result:
- A Yahoo-shaped dict containing only `None` scoring fields produced usable factors `['catalyst', 'flow', 'fundamental', 'liquidity', 'macro', 'technical', 'valuation']` and a composite score from placeholders.

Impact:
- This defeats the stated evidence-usability contract for a major data source.
- The new adapter evidence contract fixed options/short-interest/revisions, but fundamentals still have the same "unavailable data becomes neutral measured data" failure class.

### 4. CONFIRMED - store-time rejection can drop all recommendations without surfacing a run error, while the summary counts generated rather than stored insights

Files:
- `backend/analysis/autonomous_engine.py:1366-1390`
- `backend/analysis/autonomous_engine.py:1587-1617`
- `backend/analysis/autonomous_engine.py:3067-3071`
- `backend/analysis/autonomous_engine.py:3127-3138`
- `backend/analysis/autonomous_engine.py:4406-4410`
- `backend/analysis/autonomous_engine.py:4467-4477`

Failure scenario:
- Synthesis returns 3 insights.
- Each insight has an entry more than 15% from the live/pre-context price, or the store gate cannot resolve a usable price for each entry.
- `_store_insights_from_heatmap()` increments `rejected` and continues; if `stored` remains empty, no commit happens and it returns `[]`.
- The rejection is only a log warning. No `result.errors` entry is added at store time.
- The heatmap synthesis summary is built from `insights_data`, not `saved_insights`: `Generated 3 insights...` at `autonomous_engine.py:1600-1617`, while `result.insights` is empty.

Impact:
- The first fail-closed gate in `partition_by_freshness()` is reasonably surfaced through `result.errors` when every deep-dive candidate is dropped.
- The second fail-closed gate is not surfaced the same way. A realistic quote outage or stale LLM levels can produce zero stored recommendations while the run summary still says recommendations were generated.
- This is a production observability bug, not just a UX issue: callers cannot distinguish "no opportunities" from "all generated opportunities were rejected by freshness sanity checks" unless they scrape logs.

## NON-BLOCKING Issues

### 1. CONFIRMED - target banner is duplicated in several per-symbol prompts

Files:
- `backend/analysis/autonomous_engine.py:4000-4009`
- `backend/analysis/agents/technical_analyst.py:335-338`
- `backend/analysis/agents/risk_analyst.py:365-368`
- `backend/analysis/agents/sector_strategist.py:111-114`

Failure scenario:
- `_run_single_analyst()` prepends `target_banner(symbol)` whenever the formatter accepts `target_symbol`.
- The target-aware formatters also call `target_banner(target_symbol)`.
- The LLM sees the same target instruction twice.

Impact:
- Probably harmless, but it is a cross-author assumption mismatch in exactly the code that fixed the byte-identical multi-symbol prompt defect.

### 2. CONFIRMED - refreshed prices are logged as "not fresh"

Files:
- `backend/analysis/context_builder.py:978-985`
- `backend/analysis/price_freshness.py:162-167`

Failure scenario:
- A stale DB bar is successfully refreshed from a live quote.
- `build_freshness(..., refreshed=True)` returns status `refreshed`, which is usable.
- `_assess_price_freshness()` logs every status not equal to `"fresh"` as "not fresh", so successful refreshes appear in the stale warning.

Impact:
- This can make a healthy refresh path look partially broken in logs. It is not a recommendation correctness issue because `STATUS_REFRESHED` is treated as usable elsewhere.

### 3. SUSPECTED - live quote dating can overstate freshness before the US market close/open boundary

Files:
- `backend/analysis/context_builder.py:932`
- `backend/analysis/context_builder.py:1003`
- `backend/analysis/price_freshness.py:88-96`

Failure scenario:
- The pipeline runs on a weekday before the current US regular session has produced a daily close.
- `_refresh_stale_prices()` assigns `quote_date = last_weekday(as_of)`, where `as_of` is based on UTC date.
- If yfinance's quote effectively reflects the previous close or pre-market state, the snapshot is dated as the current weekday.

Impact:
- The 2-trading-day freshness contract can be overstated by one trading day around market-calendar boundaries. I did not confirm this against live yfinance behavior, so this remains suspected.

### 4. SUSPECTED - `symbol_slice` shallow-copy contract is currently okay but brittle

Files:
- `backend/analysis/symbol_slice.py:183-230`

Failure scenario:
- `build_context()` returns a 5-minute TTL-cached dict.
- `slice_context_for_symbol()` returns a new top-level dict and copies `price_freshness`, but shares nested values for `price_history`, `rich_technical`, `fundamentals`, adapters, and market-wide blocks.
- If a future formatter annotates, normalizes, sorts in place, or caches a computed value into one of those nested records under concurrent `asyncio.gather`, it will mutate the shared cached context.

Impact:
- I did not find a current formatter doing this. The module documents the hazard clearly, and current code appears read-only. Keep this as a regression risk and test target.

## TEST QUALITY Findings

1. `backend/tests/test_trade_levels_gate.py:146-186` proves only short clean strings round-trip. It does not cover LLM-shaped prose longer than 50 characters, parenthetical rationale, or truncation. `backend/tests/test_trade_levels_gate.py:299-305` explicitly blesses non-numeric entry prose bypassing the gate, which is one of the live failure modes.

2. There are no backend tests for `StatisticalFeatureCalculator._compute_seasonality_features()` or `compute_all_features()` with a normal `date` column. `rg` found no statistical calculator/seasonality tests under `backend/tests`, and the full suite passes while the `.values` crash reproduces.

3. `backend/tests/test_alpha_engine_evidence.py` tests unavailable options-flow, short-interest, and analyst-revisions payloads, but its default `_base_kwargs()` always supplies real fundamentals at lines `14-35`, and the sparse case uses `{}` at lines `121-124`. It misses the Yahoo-shaped non-empty all-None fundamentals payload that currently marks placeholder scores usable.

4. The fail-closed tests stop mostly at unit boundaries. `backend/tests/test_per_symbol_context.py:419-430` asserts all-stale candidates return an empty usable list, and `test_trade_levels_gate.py` checks rejected rows are not persisted, but there is no end-to-end assertion that result errors, phase summaries, and stored insight counts agree when all store-time entries are rejected.

5. `backend/tests/test_per_symbol_context.py:37-42` intentionally covers only the three per-symbol deep-dive analysts. That is fine for today's path, but it missed the duplicate target-banner interaction between the dispatcher and formatter-level target handling.

## WHAT IS GOOD

- The direction of the change is sound. The old per-symbol prompt defect was severe, and the new target slicing plus in-band target banner directly addresses it.
- `backend/analysis/price_freshness.py` is small, explicit, and mostly well-designed: case-insensitive lookup, dated price rendering, stale/missing/refreshed statuses, and a shared vocabulary for context builder and formatters.
- `backend/analysis/symbol_slice.py` handles case-insensitive symbol lookup and copies the most mutation-prone `price_freshness` record. I did not find a current concurrent mutation bug.
- `backend/data/adapters/evidence.py` gives the new adapters a clear unavailable-vs-usable contract, and the options-flow, short-interest, analyst-revision, and news-entity tests are concrete rather than purely mocked.
- Factor-model coverage honesty is materially better: missing factor fields are not silently rendered as six measured factors.
- The full test suite passes at the expected count.

## VERDICT

REQUEST CHANGES.

The main architecture is moving in the right direction, but the change is not yet safe to merge. Three confirmed defects are in the core promises of this branch: trade levels are still stored as corrupted prose, statistical feature computation is failing under a swallowed exception, and fundamentals still turn unavailable data into neutral measured factors. The store-time gate also needs to report rejected-vs-stored outcomes coherently, or users will see "generated" recommendations that were never persisted.
