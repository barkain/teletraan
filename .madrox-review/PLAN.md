# Teletraan — why the recommendations are weak, and the plan to fix it

Synthesis of three independent audits (Codex GPT-5.6-sol · Claude Opus 5 · Claude Fable 5),
2026-08-08, branch `feat/news-sentiment`. All findings below are code-traced or measured against
`backend/data/teletraan.db`; nothing here is speculative.

---

## The measured state of the system

| metric | value | source |
|---|---|---|
| Graded theses validated | **32 / 154 = 20.8%** | `insight_outcomes` |
| Bearish calls validated | **2 / 41 = 4.9%** (shorted names averaged **+16%**) | `insight_outcomes` |
| Bullish avg return | **+1.67%** while SPY did **+6.6%** → negative alpha, scored as 30% "success" | `price_history` |
| Confidence ≥0.80 bucket hit rate | **12.5%** (worst bucket) | reliability table |
| Confidence <0.60 bucket hit rate | 7.4% — the curve is **downward-sloping** | reliability table |
| Insights with entry/target/stop | **105 / 414 = 25%** | `deep_insights` |
| `entry_triggered` | **6 / 221 = 2.7%** — entry zones aren't near the market | `insight_outcomes` |
| Patterns fed to prompts with **zero** validated outcomes | **184 / 190** | `knowledge_patterns` |

**Confidence is anti-correlated with being right.** That is the core symptom. It is not a
prompt-tuning problem — it is five concrete broken mechanisms, below.

---

## Root causes, in dependency order

### A. The analysts are not analyzing the stock they're labeled with — *proven at runtime*

`_run_single_analyst` formats the shared multi-symbol context without slicing to the target
(`autonomous_engine.py:1331-1343`, `:1415-1417`, `:3636-3648`, `:3708-3716`). The `symbol` argument
appears only in logging metadata *after* the prompt is built.

Codex built a real context for `AAPL,MSFT` and hashed the final analyst prompt bodies:

```
PER_SYMBOL_INPUT_HASH { 'AAPL': '42bb...e485', 'MSFT': '42bb...e485', 'equal': True }
```

Byte-identical. The technical body contained AAPL twice and MSFT twice for **both** calls. Every
per-symbol deep dive is a multi-symbol prompt with a label the model never sees. This corrupts every
downstream attribution and is the single highest-leverage fix in the codebase.

### B. The prices in the prompt are up to 50 days stale, labeled "Current Price", undated

`MarketContextBuilder._get_price_history` reads only the local table and never checks recency
(`context_builder.py:777-791`); `technical_analyst.py:347-353` prints the newest surviving row as the
live price with no date. Meanwhile `_get_rich_technical` fetches **live** yfinance data for the same
symbols in the same prompt — two contradictory price universes, no reconciliation rule.

Observed 2026-08-08: DB latest for AAPL/MSFT = **2026-04-30**; live rich-technical = 2026-08-07. The
same payload emitted `No price data available for technical analysis.` *and* current fundamentals.

Consequence, from the DB — two ARM runs **fifty minutes apart** on 2026-06-19:

| id | time | entry_zone | note |
|---|---|---|---|
| 404 | 16:07:52 | **$205-215** | STRONG_BUY at ARM's April 30 close. Real price: **$439.46** |
| 409 | 16:57:04 | **$430-445** | same pipeline, same day |

Both were assigned ~the same confidence (0.52 vs 0.55). The confidence number carries no information
about whether the analysis was even grounded in reality.

### C. Missing data becomes a plausible number that moves the score

Same species as the already-fixed FinVADER bug. Measured on a live probe:

- **Options**: totals computed over `frame.head(12)` only (`options_flow.py:174-205`) — the lowest
  strikes, not the chain. AAPL adapter reported call/put volume ratio **1.02** and OI ratio **4.10**;
  full chains are **2.52** and **2.23**. Direction *and* magnitude both wrong, converted into a
  bullish `72.36` score. A failed fetch still scores a neutral 50, and `alpha_engine.py:1074-1083`
  applies any score >0 without checking `available`.
- **Short interest**: `available=bool(info)` is True when yfinance returns only
  `{'trailingPegRatio': None}` → labels an empty placeholder `low_short_interest`. Also treats
  `shortPercentOfFloat` as percentage points and subtracts 5, while yfinance returns a fraction
  (AAPL = `0.01`).
- **Analyst revisions**: scores **42.5** with every rating/target/trend field `None`.
- **News entity contamination**: the keyless adapter returned 15 articles tagged `CAT`; **≥7 were
  about other companies** — 3 Red Cat/RCAT, 4 Astec/ASTE. All scored as CAT, aggregating to
  **+0.3112 POSITIVE**, presented to the analyst as CAT company sentiment. No entity-validation stage
  exists between retrieval and scoring.
- **Factor model**: advertised as six factors; on an 11-stock probe **every** stock had
  `volatility=50, technical=50, value=50, quality=50` — only momentum and volume varied. `change_60d`
  was absent for 0/11 because the heatmap fetches only one month of history
  (`heatmap_fetcher.py:165-169`). Missing 60-day return is substituted with **zero**.
- **Partial batches cached**: `_batch_download(['AAPL','ZZZZZZZZ'])` returned only AAPL, then the
  incomplete result was served from cache in 0.000037s. Missing symbols silently dropped.

### D. The grader measures the wrong thing, late

- Success = raw move beyond **±1% absolute** over a **hardcoded 20 days**, no benchmark
  (`outcome_tracker.py:224-229`; `tracking_days=20` at `deep_engine.py:1104`,
  `autonomous_engine.py:2969,4220`). `time_horizon` is decorative — nothing reads it.
- `_HORIZON_DAYS` is keyed on `"1-2 weeks"`/`"1-3 months"` while the column actually stores
  `medium_term`/`swing`/`position` — **zero overlap**, so staleness always falls through to 30 days.
- `final_price = current_price` at evaluation time, not the price at `tracking_end_date`. Completed
  outcomes were graded on average **30.9 days late**. **61 of 67** "TRACKING" rows are already past
  their end date and will never resolve unless the app happens to be running on a scheduler slot.
- `price_history` on outcomes is a plain `JSON` column mutated in place with no `MutableList`
  (`models/insight_outcome.py:122`) — **all 221 rows have exactly 1 entry**. Max favorable/adverse
  move and every checkpoint are meaningless; `stop_triggered` is 6/221 because nothing terminates on it.
- The insight's own `entry_zone`/`target_price`/`stop_loss` play **no role** in whether it "worked."

### E. Synthesis structurally cannot adjudicate, and the prompt rewards being late

- `_flatten_analyst_reports` (`autonomous_engine.py:4012-4047`) initializes `sector_rankings`,
  `market_implications`, `divergences` and **never populates them**. The sector strategist runs and
  100% of its reasoning is discarded.
- Confidence merge is `conf = (conf + new)/2` starting from `0.0` — one 0.80 analyst becomes **0.40**;
  order-dependent, first symbol weighted 1/2ⁿ.
- `synthesis_lead.py:585` / `:775` cap at **5 technical findings and 5 risk assessments total** for a
  5-8 symbol run. Most symbols' analysis never reaches synthesis at all.
- `analysts_involved` is set from a hardcoded list / LLM prose (`synthesis_lead.py:1833`), not
  execution. Insight 409 cites a **"correlation analyst" at 0.82 confidence that never ran**, while
  `sector`, which did run, is absent.
- `ConfidenceAdjuster` weights are `BASE=0.6 + HISTORICAL=0.2` = **0.8**, applied as a sum, not a
  normalized blend (`confidence_adjuster.py:60-62` vs `:162-165`) — a flat 20% haircut on everything.
  The docstring still describes the correct 0.7/0.3 version. Result: the multi-analyst pipeline has
  **never emitted confidence above 0.82**, mean 0.521, with 77% of June insights in [0.40, 0.60].
  That *is* the "not strong enough" complaint, arithmetically.
- The prompt sets a **quota** — *"Produce {max_insights} HIGH-CONVICTION investment insights"* — with
  no path to returning fewer, and instructs *"Higher confidence for sector leaders in hot sectors /
  Lower confidence for contrarian plays"*. Confidence is defined as **agreement among analysts**
  (`synthesis_lead.py:349-354`), not probability of being right — and all analysts read the same macro
  brief first, so it rewards its own priming. `grep` for
  `disconfirm|falsifiab|base rate|counter-argument` across `backend/analysis/` returns **one** hit,
  about third-party positioning.
- `position_size` is demanded three times in the prompt and **has no column and no parser** — dropped
  on the floor. Every recommendation reaches the user unsized.

### F. Candidate selection is a 1-day momentum screen with no memory

All four windows into the ~400-name universe key on `change_1d` (`heatmap_fetcher.py:549-590`) — about
24 stocks visible. No validation that a selected symbol was even in the heatmap
(`heatmap_analyzer.py:307`), so NVDA is the primary symbol of **39/414 (9.4%)** insights. On parse
failure the analyzer returns `confidence=0.0` with `selected_stocks=[]` and **nothing checks it** —
the pipeline proceeds to analyze nothing. `parse_technical_response` returns `confidence=0.0` without
an `"error"` key, defeating both the retry loop and the flatten guard.

No prior insight is ever loaded into synthesis. Result: NVDA got 13 contradictory calls in 5 days
(`STRONG_SELL@0.88` and `BUY@0.80` in the same week); IONQ flipped SELL → BUY_MORE **13 minutes apart**.

### G. What flows back into the loop is fabricated

The loop *is* wired (patterns + track record reach the synthesis prompt) — but:
- New patterns are born with `success_rate = the extraction LLM's own confidence guess`
  (`pattern_extractor.py:691`). **184 of the 190** patterns that pass the prompt filter have
  `successful_outcomes = 0`. All 229 are `lifecycle_status='draft'`.
- `update_pattern_success_rates` re-counts **all** completed outcomes on every run, 3×/day, with no
  "already counted" marker → 8+ patterns sit at exactly `occurrences=23`, including one claiming
  **"96% over 23 occurrences"** from a single real outcome counted 22 times.
- `validate_pattern_quality` — the only statistical bar in the codebase — is **dead code**, zero call sites.
- Nothing learned ever influences **candidate selection**; only a scalar that gets multiplied by 0.2.
- There is **no evaluation harness** for the insight pipeline. No way to tell whether any change made
  recommendations better or worse.

---

## The plan

Ordered by dependency, not by appeal. Each wave is independently shippable and independently verifiable.

### Wave 1 — Stop feeding the model fiction *(highest impact, mostly mechanical)*

1. **Per-symbol evidence packets.** Fetch shared data once; slice `price_history`,
   `technical_indicators`, `rich_technical`, `fundamentals`, revisions, options, short interest and
   news to the target before formatting. Every analyst payload starts `TARGET SYMBOL: <SYM>`. Peers go
   in a separately labeled comparison block. *Test: hash two symbols' prompt bodies and assert they differ.*
2. **Freshness contract + refuse-or-abstain.** Stamp every fact with `observation_at`/`fetched_at`/
   `status`. If the newest bar is >2 trading days old, refresh from the live adapter; if that fails,
   **drop the symbol from the deep dive** rather than analyze it stale. Change "Current Price" to
   `Last Close: $X (as of DATE, Nd old)` everywhere. One price snapshot feeds current price and all
   derived technicals.
3. **Post-synthesis price sanity gate.** Reject any insight whose entry midpoint is >15% from the live
   quote, and log the rejection. *Baseline: 3 of 6 insights in the June 19 sample fail this.*
4. **Availability + units fixes** (each small, all measured): options totals over the full selected
   expiries (or a documented ATM/liquidity window) and no score on a failed chain; require ≥1 real
   field before `available=True` for revisions and short interest; normalize `shortPercentOfFloat`
   once; scorers consume only `status=ok` and renormalize weights over usable factors.
5. **News entity validation.** Resolve articles against company long name / legal aliases / exact
   ticker tokens, attach a relevance confidence, exclude low-confidence articles, and propagate fetch
   status so an outage can't read as neutral sentiment. *This branch is `feat/news-sentiment` — CAT is
   currently scored on Red Cat and Astec headlines.*
6. **Factor coverage honesty.** Fetch ≥3-6 months so `change_60d` exists; persist RSI/volatility;
   pass already-fetched fundamentals into `compute_factor_scores`; represent missing factors as
   **missing** and renormalize, never as 0 or 50; enforce a minimum coverage threshold. Retry missing
   symbols individually and never cache an incomplete batch.

### Wave 2 — Fix the grader, then rebuild the record *(you cannot improve what you mis-measure)*

7. **Rebuild `_evaluate_outcome`**: fetch the daily close series for `[start, end]` at evaluation time
   instead of polling live prices (this also resolves the 61 stuck rows retroactively and removes the
   always-on requirement); score at `tracking_end_date`; **`alpha = symbol_return − SPY_return`**;
   validated ⇔ alpha in the predicted direction beyond a threshold, **or** target hit before stop.
8. **Derive the tracking window from `time_horizon`** at all three call sites; re-key `_HORIZON_DAYS`
   to the enum values actually stored and assert membership at write time.
9. **Fix `price_history` persistence** (`MutableList` / explicit reassignment) so intraperiod data,
   max favorable/adverse move, and stop/target triggers actually work.
10. **Purge the pattern pipeline**: new patterns start `success_rate=0.5, occurrences=0` (store the
    LLM's guess separately as `extraction_confidence`); score each (outcome, pattern) pair exactly
    once; promote `draft → active` only at `occurrences ≥ 5` with Wilson lower bound > 0.5;
    `get_relevant_patterns` filters on `active` and actually uses its `symbols` argument. Wire or
    delete `validate_pattern_quality`. Reset counters and replay once.
11. **Re-score all 154 completed outcomes** under the fixed rules to get an honest baseline.

### Wave 3 — Build the measurement harness *(before touching prompts)*

12. **`eval_insights.py`**: for every directional insight past its horizon, compute symbol and SPY
    returns from local `price_history`; emit **benchmark-adjusted hit rate, mean alpha per call, and a
    confidence-decile calibration curve (ECE + Brier)**, keyed by month and by a `pipeline_version` tag
    stamped at generation time. Snapshot each run as JSON. Zero LLM cost, ~1 day, and it turns every
    subsequent change into an A/B answer instead of a vibe.

### Wave 4 — Fix the reasoning *(now measurable)*

13. **Normalize `ConfidenceAdjuster`**: `adjusted = Σ(w·v)/Σw` over available components; delete the
    unconditional `+=`; fix the docstring. *Near-zero effort, immediately restores the dynamic range
    that reads as "not strong."*
14. **Restructure synthesis input**: pass `{symbol: {technical, sector, risk}}` with each analyst's
    directional call, confidence and one-line rationale preserved. Replace `(a+b)/2` with a real
    weighted mean. Replace the global `[:5]` caps with a per-candidate evidence budget (2 strongest
    bullish, 2 bearish, 1 sector-relative, 1 invalidating), ranked by materiality before truncation.
    *Test: shuffle candidate order, assert rankings stable.*
15. **Set `analysts_involved` from actual execution**; reject any `supporting_evidence` entry
    attributed to an analyst that didn't run.
16. **Require adjudication**: add `dissent` / `dissent_resolution` columns and prompt contract — name
    the strongest view against the recommendation with its analyst and confidence; state the specific
    observable fact that makes it wrong ("on balance" rejected); **unanimity caps confidence at 0.65**
    (three analysts reading the same macro brief is correlation, not corroboration). Drop insights with
    an empty resolution.
17. **Rewrite the synthesis task block**: `max_insights` becomes an **upper bound including zero**;
    require a falsifiable thesis of the form *"X will do Y by Z because M"*, a **base rate** (unknown →
    confidence capped at 0.45), **disconfirming evidence drawn from the provided context**,
    **invalidation stated on the instrument being recommended** (the UGL call's invalidation was on gold
    spot, which the tracker doesn't hold), integer `horizon_days`, and `position_size_pct =
    risk_budget / distance_to_stop`. Anchor calibration to the real number: *"this system's realized hit
    rate is 20.8% over 154 graded calls."* Delete
    *"Higher confidence for sector leaders in hot sectors / Lower confidence for contrarian plays."*
18. **Add the missing columns** (`position_size_pct`, `base_rate`, `disconfirming_evidence`,
    `horizon_days`, numeric entry/target/stop) and **reject** rather than default-through insights
    missing levels or invalidation.
19. **Repair the funnel**: emit the full ~400-name universe as a compact table (symbol, sector, 1d, 5d,
    20d, vol_ratio, mkt_cap — a few thousand tokens); rank on a blend including 20-day relative strength
    vs sector and distance-from-20d-high so mean-reversion candidates are reachable; whitelist selected
    symbols against `heatmap_data.stocks`; **fail loudly** when `confidence == 0.0` or
    `selected_stocks == []` so the legacy fallback engages; make `parse_technical_response` set
    `"error"` like the other analysts so the retry loop fires.
20. **Give the system memory**: load open insights within horizon into synthesis — reaffirm (omit) or
    **reverse** with a `REVERSAL:` thesis naming the specific fact that changed. *Measure: same-symbol
    direction flips within 7 days without a REVERSAL prefix. Baseline: 20+, including a 13-minute IONQ flip.*
21. **Feed failures, not just a scalar**: inject the 5 most recent STRONG_FAILURE outcomes with symbol,
    action, thesis excerpt, and predicted-vs-actual alpha — into the **OpportunityHunter/DeepDive**
    prompts, not just synthesis, so learning changes *what gets picked*. Render the by-action table from
    data (e.g. *"bearish single-name calls: 2/41"*).

---

## What all three reviewers independently rejected

- **Adding more data sources** (news sentiment, prediction markets, Reddit, positioning) and **buying
  FRED/Finnhub keys.** Unanimous. Synthesis truncates to 2,000 chars/analyst and 5 findings total —
  *"pouring water into a cracked cup."* The news signal already arrives and is used as narrative
  garnish on theses whose prices were 50 days stale.
- **Restoring the macro + correlation analysts to the fan-out.** Makes the fake ensemble *worse* per
  token — all five would read the same priming brief and produce more correlated agreement, which the
  prompt then rewards with higher confidence. Independence, not headcount.
- **Hardening the JSON parsers.** The four-stage repair ladder works; the dangerous text-scraping
  fallback has fired **zero** times in 414 insights. The real bug is *inconsistent* failure signalling.
- **Logistic regression / Platt scaling over the feedback data** (FEEDBACK_LOOP_DESIGN.md phases 2 & 4).
  Calibrating against broken labels calibrates to garbage. Revisit after ≥200 correctly-labeled outcomes.
- **Surfacing confidence more prominently in the UI.** Actively harmful while the number is
  anti-correlated with accuracy.
- **Raising `max_insights` / `deep_dive_count`.** With a quota prompt and a momentum funnel, raising N
  manufactures N low-quality high-conviction claims.
- **Lowering the heatmap TTL.** 5 minutes isn't the material staleness; caching *incomplete* batches is.

## Doc correction

`CLAUDE.md` states the deep dive runs 5 specialist analysts. In `AutonomousDeepEngine` the fan-out is
restricted to `technical, sector, risk` (`autonomous_engine.py:377-380`) — and the sector output is
then discarded. Worth fixing so the docs stop asserting an ensemble that doesn't exist.
