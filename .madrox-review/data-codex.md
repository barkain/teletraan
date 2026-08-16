# Teletraan evidence-layer audit

Branch: `feat/news-sentiment`  
Audit date: 2026-08-08  
Scope: facts delivered to autonomous analysts and synthesis. No source files were changed.

## TOP 5 CONCRETE CHANGES

### 1. Give each per-symbol analyst a target-specific evidence packet

**Defect.** The code says the deep dive is per symbol, but it builds one context for the entire candidate list (`backend/analysis/autonomous_engine.py:1331-1343`) and passes that same object to every symbol task (`:1415-1417`). `_run_analysts_for_symbol` then uses the shared object unchanged (`:3636-3648`). `_run_single_analyst` formats it without the target symbol (`:3708-3716`). The `symbol` argument appears only in logging/query metadata after the prompt has already been constructed (`:3718-3730`). Technical, sector, and risk calls labelled AAPL and MSFT therefore receive identical evidence and instructions.

This is not harmless shared market context. Symbol-specific blocks contain every candidate's prices, technicals, fundamentals, revisions, and risks. The model is asked to infer which one it is supposedly analyzing from out-of-band metadata it does not see. A report can cover the wrong stock, cover all stocks, or produce inconsistent duplication. This directly destroys recommendation attribution.

**Change.** Fetch shared data once, then construct a per-target view before formatting:

- retain market, macro, sector and portfolio blocks as shared context;
- slice `price_history`, `technical_indicators`, `rich_technical`, `fundamentals`, `analyst_revisions`, options, short interest and symbol news to the target;
- start every analyst payload with `TARGET SYMBOL: AAPL`; and
- put peer/benchmark facts in a separately labelled comparison block, never in the target map.

Do not depend on the LLM query's metadata to identify the target.

**Measure.** Add a contract test that hashes the final prompt body for two symbols and asserts they differ, asserts that every target-specific section contains exactly one target, and asserts the target header. On a fixed replay set, measure (a) percentage of findings attributed to the requested symbol, (b) cross-symbol contradictions, and (c) 20/45/90-day precision and excess return of the resulting recommendations. This is the highest-impact change because it repairs every deep-dive call.

### 2. Preserve per-symbol analyst evidence through synthesis instead of taking the first five global items

**Defect.** Only technical, sector, and risk analysts run in autonomous deep dive (`backend/analysis/autonomous_engine.py:374-382`). `_flatten_analyst_reports` creates slots for all analyst types (`:4012-4019`) but merges only technical `findings` and risk `risk_assessments` (`:4028-4038`). It drops the sector report entirely, including rankings, recommendations, and rotation signals. It also drops technical observations/conflicts and risk portfolio/tail-risk observations. Its confidence calculation is an order-dependent repeated half-average, not a mean (`:4040-4045`).

The next formatter then caps technical findings at five (`backend/analysis/agents/synthesis_lead.py:582-608`) and risk items at the same global-style limit. Because reports were appended in symbol iteration order, synthesis commonly sees the first symbol's findings and none for later candidates. `_symbol` is added during flattening, but the formatter reads `finding.symbol`, so the added attribution is not even used (`autonomous_engine.py:4031-4033`; `synthesis_lead.py:586-592`). A sector LLM call can be correct and still have zero influence on the recommendation.

**Change.** Remove the lossy flattening shape. Pass synthesis a structure like `{symbol: {technical, sector, risk}}`, preserving all decision-bearing fields and explicit provenance. Format a fixed evidence budget **per candidate** (for example, two strongest bullish facts, two strongest bearish facts, one sector-relative fact, one risk/invalidating fact), followed by a cross-candidate comparison. Rank evidence by declared confidence/materiality before truncating. Compute confidence with a real weighted mean over available reports; missing reports must reduce coverage, not become zero-confidence content.

**Measure.** In tests, tag every source report field with an ID and assert that each candidate has technical, sector and risk evidence represented in the synthesis body. Track source-report coverage and candidate balance. Replay the same analyst outputs with candidate order shuffled: synthesized rankings should remain stable. Then compare recommendation precision/excess return with the old first-five formatter.

### 3. Make “usable evidence” explicit and stop unavailable, partial, or misattributed data from changing scores

**Defect.** Several adapters expose an `available` flag, but downstream scoring ignores it.

- Options failures become `expiries=[]` (`backend/data/adapters/options_flow.py:153-159`), yet the normal path computes a neutral score of 50 (`:206-252`). The alpha engine applies any score above zero without checking `available` (`backend/analysis/alpha_engine.py:1074-1083`) and counts any non-empty adapter dict as complete (`:1104-1117`). Worse, only `frame.head(12)` is totaled for calls and puts (`options_flow.py:174-205`). These are the lowest strikes, not the whole chain or an ATM/liquidity-defined sample, so the advertised call/put ratios are not market positioning.
- Analyst revisions default to neutral component scores and calculate 42.5 even with no real rating or trend (`backend/data/adapters/analyst_revisions.py:153-187`). `available=bool(trends or info)` (`:205-209`) treats yfinance's placeholder `{'trailingPegRatio': None}` as evidence. Alpha then blends 42.5 into fundamentals and catalysts (`alpha_engine.py:1081-1083`).
- Short interest has the same `available=bool(info)` error (`backend/data/adapters/short_interest.py:119-166`). It labels an empty placeholder as `low_short_interest`. It also treats `shortPercentOfFloat` as percentage points and subtracts 5 (`:142-149`), while yfinance returns a fraction (AAPL was `0.01`).
- Company news attaches the requested symbol unconditionally to every yfinance article (`backend/data/adapters/news.py:149-193`) and uses the ambiguous query `"<ticker>" stock` (`:282-300`). Dedupe and date filtering perform no entity check (`:378-417`). The sentiment pipeline then scores every headline and aggregates it as company evidence (`backend/analysis/news_intelligence.py:107-187`). Fetch failures and genuine zero coverage both become `[]` (`news.py:273-276,303-315`), which becomes neutral/stable and a “potential catalyst surprise” vacuum (`news_intelligence.py:127-150,215-245,422-428`).

These are the same species of bug as the already-fixed FinVADER issue: missing or wrong evidence becomes a plausible numeric fact and changes the recommendation.

**Change.** Define one evidence result contract: `status` (`ok`, `partial`, `unavailable`, `error`, `stale`), `source`, `observed_at`, `fetched_at`, `coverage`, and `value`. Scorers may use only `status=ok` (or explicitly coverage-weighted `partial`) and must renormalize weights over usable factors. Specifically:

- compute options totals over the complete selected expiries, or a documented ATM/delta/liquidity window; report contract coverage and do not score a failed/empty chain;
- require at least one actual revision/rating/target field for revisions and one actual short-interest field for short interest; normalize fractional short float to percent once;
- resolve news against company long name/legal aliases and exact ticker/exchange tokens, attach a relevance confidence, and exclude low-confidence articles; and
- propagate per-source news fetch status so an outage cannot be called neutral sentiment or a news vacuum.

**Measure.** Unit-test unavailable/placeholder responses and assert they do not alter score or completeness. Compare options ratios against full-chain reference totals. Label a set of ambiguous tickers (CAT, META, AI, CAR, ON) and measure company-news association precision/recall plus sentiment error against a human-curated set. In replay, ablate each alternative source and require recommendation deltas to occur only when usable evidence exists.

### 4. Build one timestamped, point-in-time snapshot and refuse stale/misaligned “current” facts

**Defect.** The context is assembled from data with incompatible clocks and little provenance.

- DB price history is filtered by a requested date window but has no freshness/status contract (`backend/analysis/context_builder.py:759-809`). Live rich technicals and fundamentals are then fetched separately (`:311-347`), allowing “no price data” and current live indicators in the same prompt.
- Sector performance has no recency cutoff or as-of field (`:909-981`). `market_summary.date` is set to now even if its SPY observation is old (`:983-1039`). Formatters call these `Current Price` and “Today's High/Low” without an observation date (`backend/analysis/agents/technical_analyst.py:348-380`; `sector_strategist.py:96-126`; `risk_analyst.py:356-362`).
- The autonomous macro scanner says it fetches macro data from yfinance (`backend/analysis/agents/macro_scanner.py:444-495`) and actually gathers only market proxies—Treasury tickers, VIX, FX, commodities, indices and sector ETFs (`:522-591`). It does not provide CPI, payrolls, unemployment, GDP, Fed funds, surprise versus consensus, release dates or revision/vintage metadata.
- The FRED adapter returns current revised observations with only observation date/value and maps both unconfigured state and errors to `[]` (`backend/data/adapters/fred.py:55-92`). ETL upserts revisions over the same observation date and stores no release/vintage timestamp (`backend/scheduler/etl.py:218-258`), so a historical replay cannot know what was available then. The alpha regime code also calculates a spread in percentage points (`backend/analysis/alpha_engine.py:271-280`) and prints it as basis points without multiplying by 100 (`:338-339`).
- Correlations drop dates when constructing frames (`backend/analysis/autonomous_engine.py:1354-1360`), then reset each return series to row positions (`backend/analysis/statistical_calculator.py:836-859`). Symbols with missing trading days are correlated against different dates.

**Change.** Construct an immutable snapshot with `observation_at`, `release_at`, `fetched_at`, `source`, units and status on every fact. Use one price snapshot for current price and all derived technicals; if the DB violates a freshness SLA, refresh from the live adapter or abstain. Never label a value “current” without its actual as-of date. Join returns by trading date before correlation. For macro, ingest releases with their publication timestamps, consensus/previous values and vintages (ALFRED-style data for historical evaluation); align low-frequency series by the time they became public, not by observation month. Correct percentage-point/basis-point conversion. If fresh macro facts are unavailable, say so and lower evidence coverage rather than letting market proxies impersonate the economy.

**Measure.** Enforce freshness/units tests at the context boundary and target a zero rate of stale facts labelled current. Deliberately age the DB in an isolated test and assert refresh-or-abstain behavior. Validate correlations against a date-joined pandas reference with missing dates. Run point-in-time replays using frozen vintages and compare both recommendation stability and 20/45/90-day performance to the current mixed snapshot.

### 5. Repair candidate discovery: the factor model currently ranks mostly momentum/volume while claiming six factors

**Defect.** Heatmap fetches only one month (`backend/analysis/agents/heatmap_fetcher.py:165-169`), so its 60-day return can never be computed (`:409-415`). It computes RSI and volatility (`:416-449`) but `StockHeatmapEntry` has no fields for them and `to_dict()` drops them (`backend/analysis/agents/heatmap_interfaces.py:48-87`; construction at `heatmap_fetcher.py:196-205`). Autonomous discovery calls `compute_factor_scores` without fundamental data (`backend/analysis/autonomous_engine.py:1157-1168`). The factor model substitutes zero for missing 60-day return (`backend/analysis/factor_model.py:207-215`) and percentile-neutral 50s for missing volatility, RSI, value and quality (`:224-291`). Under degraded weights, the constant 50 volatility and technical scores still contribute 40% of every composite, while value and quality are displayed as 50 despite carrying zero weight (`:293-313`; weight definitions at `:79-87`). Candidate selection therefore overstates factor breadth and can select the wrong stocks before the LLM analysis starts.

Partial batch failures compound this. Missing symbols are silently omitted and the partial dict is cached for five minutes (`backend/analysis/agents/heatmap_fetcher.py:260-316`); failed chunks are skipped (`:352-364`). Missing ETF returns become 0 and empty breadth becomes 0.5 (`:209-231`), fabricating neutral sector evidence.

**Change.** Fetch enough history for every declared horizon (at least 3–6 months), persist RSI/volatility/60-day return in the stock schema, and pass already-fetched fundamentals into the factor model. Represent missing factors as missing and renormalize weights per stock, with a minimum coverage threshold; do not replace missing return with zero or missing cross-sectional factors with 50. Return a completeness manifest from each batch. Retry missing symbols individually, cache successes per symbol, give errors a short separate TTL, and invalidate sector metrics below a coverage threshold.

**Measure.** Record actual factor coverage per stock and reject scores below the threshold. Test a batch containing one invalid symbol and assert that the failure is explicit and recoverable. Walk-forward test rank information coefficient, precision@K and benchmark-relative 20/45/90-day returns; compare the repaired six-factor rank with momentum-only and current degraded ranks. Also test that a partial chunk failure cannot silently change the selected candidate set.

## PROOF

All observations below came from small read-only `uv run python` probes executed in `backend/` on 2026-08-08. No full app was started.

### Identical per-symbol LLM evidence

I built one real context for `AAPL,MSFT`, formatted it along the autonomous per-symbol path, and hashed the resulting analyst input for each target:

```text
PER_SYMBOL_INPUT_HASH {
  'AAPL': '42bb...e485',
  'MSFT': '42bb...e485',
  'equal': True
}
```

The formatted technical body contained `AAPL` twice and `MSFT` twice for **both** target calls. The risk body behaved the same way. This is the direct runtime consequence of `pre_context` being reused without slicing.

### Stale DB data presented beside fresh live data

At probe time, the context timestamp was `2026-08-08T17:31:16` (Asia/Jerusalem). Latest DB observations were:

```text
AAPL  2026-04-30
MSFT  2026-04-30
SPY   2026-06-18
XLK   2026-06-18
```

`build_context(['AAPL','MSFT'])` returned zero DB `price_history`, zero stored `technical_indicators`, and zero `economic_indicators`, but two live rich-technical records (latest date `2026-08-07`) and two live fundamental records. The actual technical formatter therefore emitted:

```text
No price data available for technical analysis.
```

and later in the same payload emitted current rich technical/fundamental sections for AAPL and MSFT. The sector formatter emitted:

```text
XLK ... Price: $191.44 | Daily: +3.04% | Monthly: +25.93%
```

without saying that this was a 2026-06-18 observation. The market summary's top-level date was current while its SPY record was dated 2026-06-18.

Runtime configuration also showed `FRED=False` and `FINNHUB=False`; the economic table was empty. The actual autonomous macro payload was 2,044 characters of market proxies: 3 Treasury, 3 volatility, 1 currency, 2 commodity, 4 US-index, 4 global-index and 11 sector records. It contained no CPI, GDP, unemployment, payroll, Fed-funds value, release date, consensus surprise or vintage.

### Neutral defaults and truncated options are real score inputs

For an invalid equity ticker, the three adapter records were:

```text
options:  available=False, signal_score=50.0, sentiment=neutral
short:    available=True,  all source fields=None, squeeze_score=0.0,
          sentiment=low_short_interest
revision: available=True,  all rating/target/trend fields=None,
          revision_score=42.5
```

The surprising `available=True` values came from yfinance returning only `{'trailingPegRatio': None}`. Alpha's `bool(record)` completeness test counted all three adapter dicts, and its score path blended options 50 and revisions 42.5.

For AAPL, the options adapter scanned two expiries but only the first 12 rows on each side:

```text
adapter totals: call volume 2,481; put volume 2,421; ratio 1.02
                call OI 3,637;    put OI 886;    ratio 4.10

full chains:    call volume 172,921; put volume 68,495; ratio 2.52
                call OI 77,693;     put OI 34,858;    ratio 2.23
```

The adapter converted its truncated ratios into a bullish `72.36` score. This is not a sampling-detail issue: both direction/magnitude inputs materially changed. AAPL's yfinance `shortPercentOfFloat` was `0.01`, confirming the adapter receives a fraction while comparing it to `5.0` as if it were percent.

### News contamination changes company sentiment

The keyless news adapter returned 15 articles tagged as CAT. At least 7 were plainly about other listed companies: 3 about Red Cat/RCAT and 4 about Astec/ASTE. Examples included:

```text
Why Is RCAT Stock Lifting Off ...
Red Cat (RCAT) ...
Red Cat (NASDAQ:RCAT) ...
[four Astec/ASTE headlines]
```

All were assigned `symbols=['CAT']` and scored. The resulting CAT aggregate was `+0.3112 POSITIVE`, and the formatted analyst context presented CAT as positive company news. There is no entity-validation stage between retrieval and that score.

### “Six-factor” discovery is two varying factors plus constants

On an 11-stock live heatmap probe, every stock dictionary had only:

```text
change_1d, change_5d, change_20d, market_cap,
price, sector, symbol, volume_ratio
```

Zero of 11 had `change_60d`. Every computed score had `volatility=50`, `technical=50`, `value=50`, and `quality=50`; only momentum and volume varied. One example was:

```text
AMZN composite=61.32 momentum=83.96 volume=38.70
     volatility=50 technical=50 value=50 quality=50
```

For `_batch_download(['AAPL','ZZZZZZZZ'])`, the first call returned only AAPL in 2.216 seconds. The second call returned only AAPL in 0.000037 seconds: the incomplete batch had been cached, and the missing symbol remained silently dropped.

## REJECTED

- **“Just add fundamentals/valuation to the analyst prompt.”** Rejected. Autonomous context already requests fundamentals (`backend/analysis/autonomous_engine.py:1335-1343`), and the technical formatter appends them (`backend/analysis/agents/technical_analyst.py:540-547`). The live probe returned 27/27 expected non-null fields for both AAPL and MSFT. The real defects are target isolation and downstream loss.
- **“Just add an earnings calendar.”** Rejected as a top change. Synthesis already fetches a 30-day catalyst/earnings context (`backend/analysis/autonomous_engine.py:2416-2435`). Its accuracy should be tested, but adding another calendar does not repair the evidence-routing failures above.
- **“Reduce the heatmap TTL below five minutes.”** Rejected. Five minutes is not the material staleness observed. Caching incomplete batches, inventing neutral sector values, and using months-old DB observations as current are the accuracy failures.
- **“Send more raw OHLCV / make prompts longer.”** Rejected. Rich technical and fundamental evidence is already substantial. More multi-symbol text would worsen target confusion and synthesis truncation. The needed change is a smaller, target-specific, timestamped and balanced evidence packet.
- **“Buy/configure Finnhub and FRED keys.”** Rejected as a solution. More sources do not fix silent error/empty equivalence, availability checks, units, timestamping, or entity relevance. FRED is also absent from the autonomous macro scanner's actual LLM payload even when its adapter exists elsewhere.
- **“The existing price strategy backtest is obviously look-ahead contaminated.”** Rejected after code inspection. `run_strategy_backtest` explicitly slices each price series at each snapshot (`backend/analysis/backtester.py:706-825`). The point-in-time defect applies to revised macro/fundamental evidence and any replay of the live evidence pipeline, not that price-only walk-forward routine.
- **UI polish, explanation prose, more logs, and refactoring.** Rejected. None changes the facts scored or the decisions produced.
