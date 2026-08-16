# Teletraan — Why the recommendations are weak

Reviewer: reasoning-opus. Branch `feat/news-sentiment`. Read-only audit of `backend/analysis/**` plus
`backend/data/teletraan.db` (414 `deep_insights`, 221 `insight_outcomes`, 154 graded).

**Headline number from the system's own DB:** 32/154 graded theses validated = **20.8% hit rate**, and
confidence is *anti*-correlated with being right:

| stated confidence | n | validated | hit rate |
|---|---|---|---|
| < 0.60 | 27 | 2 | **7.4%** |
| 0.60–0.70 | 30 | 14 | 46.7% |
| 0.70–0.80 | 49 | 10 | 20.4% |
| ≥ 0.80 | 48 | 6 | **12.5%** |

The highest-conviction calls are the worst calls. That is not a prompt-tuning problem, it is four
concrete broken mechanisms. They are ranked below by expected impact.

---

## 1. The analysts are told a 50-day-old price is the "Current Price"

**Defect.** `MarketContextBuilder._get_price_history()` reads **only** the local `price_history` table
and filters `date >= utcnow() - days`. It never checks whether the newest bar is actually recent and
never falls back to a live quote:

`backend/analysis/context_builder.py:777-791`
```python
cutoff = datetime.utcnow() - timedelta(days=days)
query = (select(PriceHistory).options(selectinload(PriceHistory.stock))
         .where(PriceHistory.date >= cutoff_date))
```

`format_technical_context()` then prints the newest surviving row as the live price, **with no date
attached**:

`backend/analysis/agents/technical_analyst.py:347-353`
```python
# Current price from most recent data
current_price: float = 0.0
if prices:
    latest = prices[0]  # Prices are sorted descending by date
    current_price = float(latest.get("close", 0))
    context_parts.append(f"Current Price: ${current_price:.2f}")
```

**Why this produces weak output.** Every price artifact a user acts on — entry zone, stop, target,
20-period high/low, support/resistance — is anchored to that number. Meanwhile `_get_rich_technical()`
(`context_builder.py:529-575`) fetches **live** yfinance data for the *same* symbols in the *same*
prompt. The analyst is handed two contradictory price universes and no rule for reconciling them. And
`technical_indicators` — the third source — has **0 rows** in the DB, so `include_technical=True` is
dead weight.

**Evidence from the DB.** As of the last run, `price_history` for the deep-dive names stops at
2026-04-30; 380 of 398 symbols have a last bar of 2026-04-30 or 2026-05-01, and only 16 reach
2026-06-18. Two multi-analyst runs on **2026-06-19, fifty minutes apart**:

| id | time | symbol | entry_zone | target |
|---|---|---|---|---|
| 404 | 16:07:52 | ARM | **$205-215** | $270 (28% upside) |
| 409 | 16:57:04 | ARM | **$430-445** | $550 (live $439.46 → +25%) |
| 406 | 16:07:52 | SE | **$155-165** | $215 (35% upside) |
| 407 | 16:57:04 | SE | **$88-93** | $115 (live $91.28 → +26%) |

ARM's real price was $439.46. The 16:07 run recommended buying it at $205-215 — ARM's **April 30**
close. It also emitted `STRONG_BUY` at 0.52 confidence on that fabricated level. Five days later
insight 412 quotes "Support at $193.91, Resistance at $227.30" for a $439 stock.

**The change.**
1. In `_get_price_history`, after grouping, compute `max(date)` per symbol. If the newest bar is older
   than 2 trading days, fetch live OHLCV from the yahoo adapter for that symbol and prepend it; if the
   fetch fails, **drop the symbol from the deep-dive list** rather than analyzing it stale.
2. Stamp every price in the context with its date. Change `technical_analyst.py:352` to
   `f"Last Close: ${current_price:.2f} (as of {latest['date']}, {age_days}d old)"`.
3. Add a hard post-synthesis gate in `_store_insights_from_heatmap`: parse `entry_zone`/`stop_loss`/
   `target_price`, compare against the live quote, and **reject the insight** if the entry midpoint is
   more than 15% away from the live price. Log the rejection. A recommendation whose entry is 2x off
   is worse than no recommendation.
4. Delete the `include_technical` path or backfill `technical_indicators`; a silently-empty data source
   is a liability.

**How to measure.** Add a `price_sanity_pct = abs(entry_mid - live_price)/live_price` field on
`DeepInsight`. Today's baseline on the June 19 sample is >50% for 3 of 6 insights. Target: 100% of
stored insights below 15%. Second metric: `entry_triggered` in `insight_outcomes` is currently
**6 / 221 (2.7%)** — entry zones almost never get hit because they are not near the market. Target >60%.

---

## 2. `ConfidenceAdjuster` multiplies every conviction by 0.8 — its weights don't sum to 1

**Defect.** `backend/analysis/confidence_adjuster.py:60-62`
```python
BASE_WEIGHT = 0.6       # Weight for analyst's original confidence
HISTORICAL_WEIGHT = 0.2 # Weight for historical track record
THEMATIC_WEIGHT = 0.1   # Weight for thematic track record (when available)
```
`confidence_adjuster.py:162-165`
```python
adjusted = (
    base_confidence * self.BASE_WEIGHT
    + historical_accuracy * self.HISTORICAL_WEIGHT
)
```
0.6 + 0.2 = **0.8**. This is not a weighted average, it is a 20% haircut applied to everything. The
docstring at `confidence_adjuster.py:100` still describes the correct version — `adjusted = (base * 0.7)
+ (historical * 0.3)` — so the constants were changed and the formula was not. `THEMATIC_WEIGHT` is
supposed to carry the missing mass but is (a) conditional on `thematic_total >= 3` and (b) *added on
top* rather than being part of a normalized blend (`confidence_adjuster.py:171-181`).

Plug in the real numbers: historical accuracy = 0.208, so `adjusted ≈ 0.6·base + 0.042`. A 0.90
conviction becomes 0.58. A 0.50 becomes 0.34.

**Evidence from the DB.** Split by pipeline (the `alpha_engine` path bypasses the adjuster):

| source | n | min | max | mean |
|---|---|---|---|---|
| alpha_engine (no adjuster) | 50 | 0.779 | 0.950 | **0.857** |
| multi-analyst (through adjuster) | 172 | 0.300 | **0.820** | **0.521** |

In June, **73 of 95** multi-analyst insights (77%) land in [0.40, 0.60]. The main pipeline has never
once emitted a conviction above 0.82. Every recommendation reads "about a coin flip," which is exactly
the "not strong" complaint.

**Compounding defect — the track record being fed in is itself garbage.** The 0.208 accuracy comes from
a grader that ignores the insight's own stated horizon. `tracking_days=20` is **hardcoded** at
`autonomous_engine.py:2969` and `autonomous_engine.py:4220`, so a `long_term` (3+ month) thesis and a
`swing` (1-4 week) thesis are both marked to market at 28 calendar days. `time_horizon` is decorative —
nothing reads it. Worse, `_HORIZON_DAYS` in `outcome_tracker.py:24-30` is keyed on `"1-2 weeks"`,
`"1-3 months"`, … while every value actually written to the column is `medium_term` / `short_term` /
`swing` / `position` — **zero overlap**, so `compute_staleness()` always falls through to the 30-day
default. And validation is a naive mark-to-market that ignores entry/stop/target entirely
(`outcome_tracker.py:224-231`): `thesis_validated = actual_return > 1.0` for bullish. For `neutral`
(HOLD/WATCH) it requires `-1.0 <= return <= 1.0` — a stock must move less than 1% over the whole window
to "validate," which is why HOLDs almost never pass. The deflated hit rate then flows back into the
adjuster and deflates the next run's confidence. Closed loop of miscalibration.

**The change.**
1. Fix the blend to normalize: `w_total = BASE + HIST + (THEMATIC if available else 0)`, then
   `adjusted = (base*BASE + hist*HIST + thematic*THEMATIC) / w_total`. Delete the unconditional `+=` at
   line 177. Update the stale docstring.
2. Replace `tracking_days=20` at both call sites with a mapping off the insight's own `time_horizon`:
   `{"immediate":3, "swing":10, "short_term":21, "near_term":21, "position":60, "medium_term":60,
   "long_term":120}`; refuse to track anything that maps to `unknown`.
3. Re-key `_HORIZON_DAYS` to the enum values actually stored, and assert at write time that
   `time_horizon` is in that set.
4. Grade against the trade, not the calendar: in `check_price_level_triggers`, terminate tracking when
   `stop_triggered` (→ FAILURE) or `target_triggered` (→ SUCCESS) fires, and use `entry_zone` as the
   cost basis when `entry_triggered`. `stop_triggered` is currently **6/221** because nothing
   terminates on it.
5. Report a Brier score, not a hit rate. Add `brier = mean((confidence - validated)^2)` to the track
   record and feed **that** back into the prompt.

**How to measure.** Reliability curve: bucket by stated confidence, plot realized hit rate. Today the
line is downward-sloping (7.4% → 46.7% → 20.4% → 12.5%). Target: monotonically increasing, and Brier
score below the 0.208 base-rate-only benchmark. Second metric: the interquartile range of stored
confidence — currently ~0.11 for the main pipeline; a system that discriminates should show ≥0.25.

---

## 3. The Synthesis Lead cannot adjudicate — it is shown a mutilated summary, not the disagreement

**Defect A: two of three analysts' reasoning is deleted before synthesis.**
`backend/analysis/autonomous_engine.py:4012-4047`
```python
aggregated: dict[str, Any] = {
    "technical": {"findings": [], "confidence": 0.0},
    "macro": {"market_implications": [], "confidence": 0.0},
    "sector": {"sector_rankings": [], "confidence": 0.0},
    "risk": {"risk_assessments": [], "confidence": 0.0},
    "correlation": {"divergences": [], "confidence": 0.0},
}
for symbol, reports in analyst_reports.items():
    for analyst_name, report in reports.items():
        ...
        if analyst_name == "technical":
            aggregated["technical"]["findings"].extend(findings)
        elif analyst_name == "risk":
            aggregated["risk"]["risk_assessments"].extend(assessments)
```
`sector_rankings`, `market_implications` and `divergences` are initialized empty and **never
populated**. The sector strategist is one of only three analysts that actually run, and 100% of its
reasoning is discarded — `_format_sector_report` (`synthesis_lead.py:708-741`) reads exactly those
empty lists, so the Synthesis Lead receives a Sector section containing a market-phase string and
nothing else.

**Defect B: the confidence merge is a broken running average.** `autonomous_engine.py:4041-4045`
computes `conf = (conf + new) / 2` starting from `0.0`. With one symbol, a 0.80 analyst becomes
**0.40**. With confidences [0.9, 0.5, 0.5] it yields 0.4875 instead of 0.633, and the first symbol
carries weight 1/2ⁿ. Analyst confidence reaching synthesis is systematically halved and order-dependent.

**Defect C: only 5 findings survive across the whole run.** `synthesis_lead.py:585` (`for f in
findings[:5]`) and `synthesis_lead.py:775` (`assessments[:5]`). A run deep-dives 5-8 symbols. The
Synthesis Lead sees at most 5 technical findings and 5 risk assessments *total* — most symbols'
analysis never reaches it at all.

**Defect D: the prompt never asks for adjudication.** `SYNTHESIS_LEAD_PROMPT` at
`synthesis_lead.py:236-241` is the entire conflict-resolution machinery:
> ## Conflict Resolution Rules
> - Technical + Macro alignment = HIGH confidence
> - Technical conflicts with Macro = Favor Macro for >1 month horizons, Technical for <1 month
> - Risk warnings override bullish signals if tail risk probability >15%

That is a lookup table, not adjudication. There is no requirement to *name* the dissenting analyst, to
*state what the dissent would imply if correct*, or to *lower conviction when dissent is unresolved*.
The output schema has no field for it. `conflicting_signals` exists only in the run-level `summary`
(`synthesis_lead.py:305`), never on the insight the user reads.

**Defect E: the ensemble is fake, and the attribution is fabricated.** `ANALYSTS` at
`autonomous_engine.py:377-380` restricts the fan-out to `technical`, `sector`, `risk` — macro and
correlation never run per-symbol (CLAUDE.md still says "5 specialist analysts"). All three receive an
**identical** `discovery_context` prefix (`autonomous_engine.py:3716`:
`full_context = f"{discovery_context}\n\n{formatted_context}"`) containing the macro regime call, the
heatmap analyst's patterns, and the per-stock selection *rationale*. They are anchored on the same
directional prior before they see any data. Then `parse_autonomous_insights` defaults
`analysts_involved` to a hardcoded five-name list (`synthesis_lead.py:1833`).

Real output, insight **409** (`ARM`, 2026-06-19): `analysts_involved = ["technical","correlation","risk"]`
with a `correlation` evidence entry at 0.82 confidence — **the correlation analyst does not run in this
pipeline**. The Synthesis Lead invented a corroborating analyst. Meanwhile `sector`, which *did* run, is
absent. Across the DB, `analysts_involved` takes 12+ distinct values including
`["technical","sector","correlation","risk"]` — it is LLM prose, not a record of execution.

**The change.**
1. Populate all five branches in `_flatten_analyst_reports`, or better: stop flattening. Pass the
   synthesis lead a **per-symbol** block containing each analyst's `action_bias`/`bias`, confidence, and
   one-line rationale, so it can see *"for ARM: technical BUY 0.78, sector UNDERWEIGHT 0.82, risk
   AVOID 0.76"*. Today it structurally cannot see that.
2. Replace the `(a+b)/2` merge with `statistics.mean(values)` over a collected list.
3. Raise the `[:5]` truncations to `len(symbols) * 3`, or key them per-symbol.
4. Set `analysts_involved` from the actual `reports.keys()` where `"error" not in report` — never from
   the LLM. Reject any `supporting_evidence` entry whose `analyst` is not in that set.
5. Rewrite the conflict section and add two required output fields. Replace lines 236-241 with:

> ## Adjudication (required)
> You will receive, per symbol, each analyst's directional call and confidence. For every insight you
> emit you MUST fill two fields:
> - `"dissent"`: the strongest analyst view *against* your recommendation, quoted with the analyst's
>   name and confidence. If literally every analyst agreed, write `"unanimous"` and treat that as a
>   *warning* — unanimity among three analysts who read the same macro brief is correlation, not
>   corroboration, and caps your confidence at 0.65.
> - `"dissent_resolution"`: what specific, observable fact makes the dissenter wrong. "Weighing the
>   evidence," "on balance," and "while risks exist" are not resolutions and will be rejected.
>
> Confidence is capped by dissent: if the dissenting analyst's confidence exceeds your primary
> supporting analyst's, your insight confidence may not exceed 0.55, regardless of how many analysts
> agree with you. Never cite the *number* of agreeing analysts as a reason for conviction.

6. Add `dissent` / `dissent_resolution` columns to `DeepInsight`, extract them in
   `parse_synthesis_response` (`synthesis_lead.py:966-985`), and **drop any insight where
   `dissent_resolution` is empty**.

**How to measure.** % of insights with a non-empty, non-boilerplate `dissent_resolution` (baseline: the
field doesn't exist). Then re-run the confidence-vs-hit-rate table: the ≥0.80 bucket should stop being
the worst bucket. Also track: fraction of `supporting_evidence` entries attributed to an analyst that
actually executed — currently demonstrably below 100%.

---

## 4. Deep-dive candidates are yesterday's biggest movers, and the system has no memory of what it said yesterday

**Defect A: the funnel is a 1-day momentum screen.** The heatmap analyzer prompt tells the LLM it is
looking at a treemap "of the S&P 500" and asks it to "select 10-15 specific individual stocks"
(`heatmap_analyzer.py:71`). But `format_heatmap_for_llm` — the only thing it actually sees — exposes
individual stocks through exactly four windows, **all keyed on `change_1d`**
(`heatmap_fetcher.py:549-590`):

```python
sorted_stocks = sorted(data.stocks, key=lambda s: s.change_1d, reverse=True)
lines.append("### Top 5 Gainers (1D)")
for s in sorted_stocks[:5]: ...
lines.append("### Top 5 Losers (1D)")
for s in sorted_stocks[-5:]: ...
divergences = data.get_divergences()          # [:8]
outliers = data.get_outliers(change_field="change_1d", threshold_std=2.0)   # [:6]
```

Out of a ~400-name universe, roughly 24 stocks are visible, selected by **one day of price change**. No
valuation, no earnings trajectory, no 20-day trend, no mean-reversion screen ever enters candidate
selection. The prompt's own worked example is a pure momentum chase — *"Leading the tech momentum with
outsized 1d gain of +3.2%"* (`heatmap_analyzer.py:117`) — and the selection criteria reinforce it:
*"Higher priority for stocks where multiple signals converge."*

**Defect B: nothing validates that a selected symbol was in the heatmap.**
`parse_heatmap_analysis_response` takes `s.get("symbol", "UNKNOWN")` verbatim
(`heatmap_analyzer.py:307`). The LLM can and does name tickers from memory. Result:
**NVDA is the primary symbol of 39 of 414 insights (9.4%)**, GC=F 23, LITE 17, across only 116 distinct
symbols.

**Defect C: a failed upstream phase poisons everything silently.** On parse failure
`parse_heatmap_analysis_response` returns `HeatmapAnalysis(overview="Parse error...", confidence=0.0)`
with `selected_stocks=[]` (`heatmap_analyzer.py:262-267`). Nothing checks `confidence == 0.0`. The
pipeline proceeds to `symbols_to_analyze = [s.symbol for s in ordered_selections[:deep_dive_count]]`
(`autonomous_engine.py:1213-1215`) → empty list → deep dive analyzes nothing → synthesis runs on nothing.
Same shape in the technical analyst: `parse_technical_response` returns
`TechnicalAnalysisResult(confidence=0.0)` **without an `"error"` key**
(`technical_analyst.py:578-585`), so `_flatten_analyst_reports`' `if "error" in report: continue` guard
misses it, and a parse failure is merged in as a real 0.0-confidence report. It also doesn't raise, so
`_run_single_analyst`'s retry loop (`autonomous_engine.py:3724-3747`) never fires — a garbled technical
response is accepted on the first attempt. Risk, macro and sector *do* set `"error"`; technical and
heatmap don't. The inconsistency is the bug.

**Defect D: total amnesia between runs.** No prior `DeepInsight` is ever loaded into the synthesis
context. `lifecycle_state` exists on the model but is only ever read for `ThematicInsight`
(`autonomous_engine.py:733,754`) — never for stock insights. The only historical input is an aggregate
success-rate string from `build_track_record_context`.

**Evidence.** NVDA, 2026-02-10 → 02-15, thirteen insights in five days:
`SELL@0.88, WATCH@0.48, SELL@0.93, HOLD@0.81, STRONG_SELL@0.88, BUY@0.65, BUY@0.80, HOLD@0.85,
SELL@0.80, SELL@0.79, SELL@0.72, HOLD@0.68, HOLD@0.70`. IONQ flipped `SELL` (id 254, 13:55) →
`BUY_MORE` (id 272, 14:08) — **thirteen minutes apart**. GOOGL `SELL` (07:48) → `BUY` (22:41) same day.
The system is not forming views; it is re-reading the tape each morning with no recollection and no
obligation to explain the reversal.

**The change.**
1. Emit the full universe to the heatmap analyzer as a compact table (symbol, sector, 1d, 5d, 20d,
   vol_ratio, mkt_cap) — ~400 rows is a few thousand tokens. Rank the pre-screen on a blend, not
   `change_1d` alone: at minimum add 20-day relative strength vs sector and a distance-from-20d-high
   term so mean-reversion candidates are reachable.
2. Add a whitelist check in `parse_heatmap_analysis_response`: drop any `symbol` not present in
   `heatmap_data.stocks`. Log the drops.
3. Fail loudly. If `heatmap_analysis.confidence == 0.0` or `selected_stocks` is empty, raise so the
   existing legacy-pipeline fallback at `autonomous_engine.py:1090` engages. Make
   `parse_technical_response` set `"error"` on parse failure like the other three, and re-raise so the
   retry loop runs.
4. Load open insights into synthesis. Query `DeepInsight` where `lifecycle_state == 'active'` and
   `created_at` within the horizon, and prepend a block:

> ## Your Open Positions
> You previously issued these recommendations and they are still live. For each symbol below you must
> either (a) **reaffirm** — omit it from this run's output entirely, or (b) **reverse** — emit a new
> insight whose thesis begins with "REVERSAL:" and names the specific fact that changed since
> {date}. A price move alone is not a fact that changed; cite a catalyst, a data release, or a broken
> level from your own stated invalidation trigger. You may not silently contradict yourself.
>
> {open_insights_table}

**How to measure.** Count same-symbol direction reversals within 7 days without a `REVERSAL:` prefix.
Baseline from the DB: 20+ contradictory pairs, including three IONQ flips within 48h and a 13-minute
flip. Target: 0 unexplained. Second metric: Herfindahl index on `primary_symbol` — NVDA at 9.4% of all
insights should drop below 4%.

---

## 5. The prompts do not force a falsifiable brief — and the one field that would size the risk is thrown away

**Defect.** Across the entire `backend/analysis/` tree, `grep -ri "disconfirm|falsifiab|bear case|
counter-argument|base rate|steelman|what would prove.*wrong"` returns **exactly one hit**, and it is
about third-party investor positioning, not the system's own thesis (`synthesis_lead.py:386`).

The autonomous pipeline's *actual* synthesis prompt is worse than the legacy one. `AUTONOMOUS_SYNTHESIS_PROMPT`
(`synthesis_lead.py:1520-1603`) asks for 13 numbered fields and **none of them is an invalidation
trigger, a historical precedent, a base rate, or a position size**. Its selection criteria are an
explicit instruction to chase and to punish contrarianism:

`synthesis_lead.py:1559-1566`
```
### Selection Criteria:
- Prioritize opportunities that ALIGN with macro themes and sector rotation
- Favor setups with clear risk/reward (minimum 2:1)
- Include mix of opportunity types if possible ...
- Higher confidence for sector leaders in hot sectors
- Lower confidence for contrarian plays
```

"Higher confidence for sector leaders in hot sectors" is a directive to be most confident precisely when
a name is most extended — and combined with the 1-day-momentum funnel (§4) it means the system's
strongest calls are structurally late. `synthesis_lead.py:1543` compounds it: *"Produce {max_insights}
HIGH-CONVICTION investment insights"* — a **quota**. The model must emit N ideas whether or not N good
ones exist, and must call them high-conviction. There is no "return fewer" escape hatch and no
`max_insights=0` path.

The calibration guidance is circular. `synthesis_lead.py:349-354`:
```
## Confidence Scoring
- 0.8-1.0: Multiple analysts agree with high individual confidence
- 0.6-0.8: Majority agreement or strong single-analyst signal with corroboration
```
Confidence is defined as *agreement among analysts*, not as *probability of being right*. Given §3 —
three analysts primed by an identical macro brief — this reduces to "be confident when your own priming
worked." It is not tied to any observable frequency.

**And `position_size` is collected and silently discarded.** `SYNTHESIS_LEAD_PROMPT` demands it three
times (`synthesis_lead.py:266`, `:289`, `:396` — *"include entry_zone, target, stop_loss, and
position_size fields with specific values"*). But there is **no `position_size` column on `DeepInsight`**
(`models/deep_insight.py:53-177`) and `parse_synthesis_response` never extracts it
(`synthesis_lead.py:966-985`). The LLM writes "5-7% of portfolio," and it is dropped on the floor.
Every recommendation reaches the user unsized.

**Evidence.** 309 of 414 insights (**75%**) have `entry_zone`, `target_price` and `stop_loss` all NULL.
66 have no `historical_precedent`. The precedents that do exist are unfalsifiable cherry-picks —
insight 38 (`STRONG_BUY UGL @ 0.89`) cites *"1970s stagflation: Gold rose from $35 (1971) to $850
(1980) = 24x gain over decade"* and *"Current setup 81% similar"*, an invented similarity score with no
sample, no failure cases, no base rate. It returned **-12.67% (STRONG_FAILURE)**.

**The change.** Rewrite `AUTONOMOUS_SYNTHESIS_PROMPT`'s task block. Replace lines 1543 and 1559-1566
with:

> ## Your Task
> Produce **up to** {max_insights} insights. Emitting fewer — including zero — is a correct answer when
> the evidence does not support more. You will be scored on realized accuracy, not on count.
>
> Every insight must contain, or it will be discarded:
>
> 1. **THESIS** — one falsifiable sentence of the form *"X will do Y by Z because M"*, where Y is a
>    price or measurable outcome, Z is a date, and M is a mechanism. Not "positioned to benefit from,"
>    not "well-placed for."
> 2. **BASE_RATE** — how often has this specific setup worked, over how many observations, and where
>    does that number come from? If you do not know, write `"unknown — no base rate"` and cap your
>    confidence at 0.45. Do not substitute one memorable historical analogy for a frequency.
> 3. **DISCONFIRMING_EVIDENCE** — the strongest fact in the provided context that argues *against* this
>    trade. It must be a fact from the context, not a generic risk. "Valuation is stretched" and
>    "macro uncertainty" are rejected. If you cannot find one, you have not read the context.
> 4. **INVALIDATION** — a single price level or dated event, stated **on the instrument you are
>    recommending**, that proves the thesis wrong. "Gold below $4,900" is invalid for a UGL
>    recommendation; state it in UGL terms.
> 5. **HORIZON_DAYS** — an integer. This is the window your call will be graded over.
> 6. **POSITION_SIZE_PCT** — a number, derived as `risk_budget_pct / distance_to_stop_pct`, capped at
>    8%. A wider stop must produce a smaller position. Show the arithmetic.
> 7. **CONFIDENCE** — your probability that the thesis is validated within HORIZON_DAYS. Calibration
>    anchor: this system's realized hit rate is **20.8% over 154 graded calls**. A confidence above
>    0.60 asserts you are three times better than that baseline on this specific idea; justify it in
>    one clause or lower the number. Agreement between analysts is not justification.

Then: add `position_size_pct`, `base_rate`, `disconfirming_evidence`, `horizon_days` columns to
`DeepInsight`; extract them in both parsers; and **reject** any insight missing `invalidation`,
`disconfirming_evidence`, or trading levels rather than defaulting it through
(`synthesis_lead.py:988` currently admits anything with a title and a thesis).

**How to measure.** (a) % of insights with all seven fields populated — baseline 0%, since four of the
fields do not exist and 75% lack levels. (b) Blind-grade 20 theses against the *"X will do Y by Z
because M"* template; baseline on the insights quoted in PROOF below is 0/4. (c) Once §2's grader is
fixed, compare realized hit rate for insights whose `disconfirming_evidence` was substantive vs
boilerplate — if forcing the step doesn't move accuracy, the step is theater and should be cut.

---

# PROOF

Real records from `backend/data/teletraan.db`, quoted verbatim.

### A. The three-times-repeated highest-conviction call was the worst loss

Three insights on UGL (2x leveraged gold) inside 48 hours — id 38 (02-10 07:18, `STRONG_BUY`, 0.89),
id 43 (02-10 21:24, `STRONG_BUY`, 0.84), id 51 (02-12 00:08, `BUY`, 0.85). Outcomes: **-12.67%,
-10.89%, -12.91%, all STRONG_FAILURE.**

> **id 38 thesis:** "UGL (110 shares, 5.7% allocation) is your ONLY position aligned with stagflation
> regime and should be INCREASED to 15-20% immediately. **All analysts converge:** Macro says gold
> $5,056 (+10.19%) signals commodity cycle beginning (**1970s analog 81% match** = gold 24x over
> decade). Risk says VIX mispriced = flight to safety accelerating. Correlation says gold leading SPY
> by 5-15 days…"
>
> **id 43 thesis:** "Your 5.7% UGL (2x Gold) position is PERFECTLY positioned for current regime.
> **All 5 analysts identify** gold strength (+10.02%) as smart money positioning for tail risks."
>
> **id 51 thesis:** "Gold at $5,107 (+10.41%) is pricing CRISIS while VIX at 17.65 prices NORMAL =
> **92% confidence divergence resolves** with vol spike…"

What makes this weak, precisely:
- **Unanimity is used as the load-bearing argument** ("All analysts converge", "All 5 analysts
  identify"). Per §3, only three analysts run and all three read the same macro brief first. The
  prompt (`synthesis_lead.py:350`) *instructs* the model to treat agreement as 0.8-1.0 confidence. The
  system is rewarding its own priming.
- **id 43 credits "all 5 analysts"** — macro and correlation did not run.
- **Invented probabilities.** "81% match" and "92% confidence" have no computation behind them
  anywhere in the codebase. They are LLM-generated numerals that read as rigor.
- **Cherry-picked precedent, no base rate.** "1970s stagflation: Gold +2,300%" is the single best case
  in history. No count of how often a stagflation call preceded a gold drawdown.
- **Invalidation on the wrong instrument.** "Gold closes below $4,900" — the tracked position is UGL at
  $74.49. The tracker holds no gold-spot series, so the stated invalidation was never checkable. Across
  the DB: `stop_triggered = 6 / 221`.
- **No levels at all.** `entry_zone`, `target_price`, `stop_loss` are NULL on all three. No sizing —
  yet the thesis says "should be INCREASED to 15-20%," which is a size recommendation that the schema
  cannot store or verify.
- **Confidence rose on repetition without new evidence** (0.84 → 0.85 → 0.89 across the three).

### B. The same ticker, two runs, fifty minutes apart, at 2x different prices

| id | time (2026-06-19) | symbol | action | conf | entry_zone | target |
|---|---|---|---|---|---|---|
| 404 | 16:07:52 | ARM | STRONG_BUY | 0.52 | $205-215 | $270 (28% upside) |
| 409 | 16:57:04 | ARM | BUY | 0.55 | $430-445 | $550 (live $439.46 → +25%) |
| 406 | 16:07:52 | SE | BUY | 0.51 | $155-165 | $215 (35% upside) |
| 407 | 16:57:04 | SE | BUY | 0.53 | $88-93 | $115 (live $91.28 → +26%) |

Both runs are the multi-analyst pipeline (neither is `alpha_engine`). ARM traded at $439.46. The 16:07
run issued a `STRONG_BUY` at ARM's **2026-04-30** close — the newest bar in `price_history`, which the
prompt labels "Current Price" with no date (§1). Note also that both runs assign essentially the same
confidence (0.52 vs 0.55) to a correct-price call and a 50-day-stale call. The confidence number carries
no information about whether the analysis was even grounded in reality.

### C. A "correlation analyst" that does not exist, and a thesis that argues against itself

**id 409, `BUY ARM @ 0.5466`, 2026-06-19.** `analysts_involved = ["technical","correlation","risk"]`.
The autonomous pipeline runs `technical`, `sector`, `risk` (`autonomous_engine.py:377-380`). The
correlation analyst never executed — but here is its evidence entry, at the *highest* confidence in the
insight:

> `{"analyst": "correlation", "finding": "ARM leading semiconductor momentum surge as statistical
> outlier in AI chip plays", "confidence": 0.82, "data_points": ["Diverging +5.69% vs Tech sector
> -0.34%", "Institutional accumulation pattern"]}`

The `sector` analyst, which *did* run, is absent from the attribution. The thesis:

> "The stock is exhibiting **parabolic momentum** (+5.69% today, +36.25% over 5 days on 2.6x volume)…
> The heatmap shows ARM as a clear statistical outlier indicating institutional accumulation…
> **While stochastic is elevated at 81.9, parabolic momentum names often extend before mean-reverting.**
> The risk is sized appropriately given volatility."

This is the §4 funnel and the §5 prompt in one paragraph: the *reason* the stock was selected is that it
was yesterday's biggest mover; the overbought reading is acknowledged and then waved away with an
unquantified folk claim ("often extend"); "the risk is sized appropriately" is asserted with no size
anywhere in the record. And the risk analyst's own evidence flags the data problem out loud, with no
mechanism to act on it:

> `"data_points": ["Max drawdown 31%", "Stop at $188 (stale - adjust to $395)"]`

**Five days later, id 412, `HOLD ARM @ 0.77`:**

> "ARM's **-10.14% collapse today** represents the largest statistical outlier in the heatmap… the
> 21.5% max drawdown projection with only 0.8x risk/reward makes this **uninvestable near-term**."
>
> evidence: `{"analyst": "technical", …, "confidence": 0.45, "data_points": ["Support at $193.91",
> "Resistance at $227.3"]}`

A $439 stock cannot have resistance at $227.30. The technical analyst dissented at **0.45** while the
synthesis emitted **0.77** — higher than the majority of its own evidence, with the disagreement
recorded nowhere the user can see. And there is no acknowledgment anywhere in id 412 that this same
system issued a BUY on the same ticker five days earlier: no reversal statement, no accounting.

### D. Thirteen contradictory calls on NVDA in five days

`2026-02-10` → `2026-02-15`, `primary_symbol = 'NVDA'`, in order:

```
SELL@0.88, WATCH@0.48, SELL@0.93, HOLD@0.81, STRONG_SELL@0.88, BUY@0.65, BUY@0.80,
HOLD@0.85, SELL@0.80, SELL@0.79, SELL@0.72, HOLD@0.68, HOLD@0.70
```

A `STRONG_SELL` at 0.88 and a `BUY` at 0.80 on the same instrument in the same week. IONQ:
`SELL` (id 254, 2026-05-05 13:55) → `BUY_MORE` (id 272, 2026-05-05 **14:08**), thirteen minutes apart.
GOOGL: `SELL` (id 108, 02-14 07:48) → `BUY` (id 121, 02-14 22:41).

Nothing in the codebase loads a prior open insight into the synthesis context. The confidence attached
to each of these is drawn from the same 0.6-1.0 "analysts agree" band, so a user reading any one of
them sees high conviction and no indication that the opposite call was made yesterday at equal
conviction.

### E. Directional bias: bearish calls are near-inverted

| predicted_direction | n | validated | avg return |
|---|---|---|---|
| bullish | 89 | 27 (30%) | +1.67% |
| bearish | 41 | **2 (4.9%)** | **+16.00%** |
| neutral | 24 | 3 (12.5%) | +11.79% |

The system's bearish calls were right 5% of the time, and the names it said to avoid rose an average of
16%. This is the §4 funnel again from the other side: the "Top 5 Losers (1D)" window feeds
`STRONG_SELL`/`AVOID` on names that just gapped down — i.e. it sells the low. A 4.9% hit rate on a
binary direction call is information, inverted; nothing in the pipeline notices or exploits it, because
the track record is consumed only as a scalar success rate that gets multiplied by 0.2 (§2).

---

# REJECTED

Plausible-sounding ideas I looked at and concluded are **not** worth doing.

**1. Harden the JSON parsers / migrate to structured tool-call outputs.**
This looks like the obvious "parse failures degrade silently" finding, and it is largely already solved.
`_extract_json` → `_strip_json_comments` → `_repair_llm_json` → `_salvage_insight_objects`
(`synthesis_lead.py:1073-1176`) is a well-built four-stage ladder that recovers individual insight
objects via anchored `raw_decode`. And the text-scraping fallback `_extract_insights_from_text`
(`synthesis_lead.py:1955-2002`), which *would* be a real hazard — it regex-harvests ALL-CAPS words as
tickers and emits `thesis="See full analysis for details."` at confidence 0.4 — has produced **zero
rows** in 414 insights (`SELECT count(*) ... WHERE thesis LIKE '%See full analysis for details%'` → 0).
It has never fired. **Worth doing anyway (5 min, no reward):** delete `_extract_insights_from_text` and
the `_run_single_analyst` `{"raw": ..., "confidence": 0.5}` branch at `autonomous_engine.py:3738` so
they can't fire later. The *inconsistent* failure signalling in §4C (technical returns confidence=0.0
with no `"error"` key, defeating both the retry loop and the flatten guard) is the part that matters —
that's the fix, not more parser layers.

**2. Add back the macro economist and correlation detective to the per-symbol fan-out.**
Restoring 5 analysts sounds like it fixes the "fake ensemble," but it makes it *worse* per token: all
five would receive the same `discovery_context` prefix (`autonomous_engine.py:3716`) and produce more
correlated agreement, which the prompt then rewards with higher confidence
(`synthesis_lead.py:350`). Independence, not headcount, is the missing ingredient. If you want a real
ensemble, withhold the macro regime call from one analyst and require it to derive its own view — but
that is a bigger change than §3 and should wait until §3's dissent field proves disagreement is being
captured at all.

**3. Enrich the context with more alternative data (news sentiment, prediction markets, Reddit,
investor positioning).**
This branch is named `feat/news-sentiment` so it's the natural next move, but the wiring already exists
(`synthesis_lead.py:356-372`, `autonomous_engine.py:517-641`) and it cannot help while §1 and §3 hold.
Insight 409 cites *"News sentiment is POSITIVE (+0.45)"* and insight 412 cites *"NEUTRAL (+0.09) but
DETERIORATING"* — the signal arrived and was used as narrative garnish on a thesis whose price levels
were 50 days stale. Adding a sixth data feed to a synthesis step that can only see 5 technical findings
and zero sector reasoning is pouring water into a cracked cup.

**4. Enforce the "never recommend a sector ETF" rule harder.**
`SYNTHESIS_LEAD_PROMPT:210` spends its most emphatic language on this ("CRITICAL: … NEVER recommend a
sector ETF"), and it is partly ignored anyway — XLE is the primary symbol of 15 insights. But this is
a *style* constraint, not an accuracy constraint: XLE at least has a real, liquid, correctly-priced
quote. Tightening it changes which instrument a wrong call is expressed in, not whether the call is
right. Low priority until §1-§3 land. (It also actively costs something: the rule pushes the model from
a diversified sector expression toward a single-name bet, which raises variance on a system with a 20.8%
hit rate.)

**5. Make the frontend surface confidence/conviction more prominently, or add a conviction badge.**
Explicitly out of scope per the brief, and actively harmful here: the confidence number is
anti-correlated with accuracy (7.4% hit rate in the <0.60 bucket vs 12.5% at ≥0.80). Making a
mis-calibrated number more visible increases the damage it does. Fix §2 first; only then is the number
worth showing.

**6. Increase `max_insights` / `deep_dive_count` for broader coverage.**
More candidates through a funnel biased toward 1-day movers (§4) yields more momentum chases, not more
edge. The quota framing at `synthesis_lead.py:1543` ("Produce {max_insights} HIGH-CONVICTION
investment insights") means raising N directly manufactures N low-quality high-conviction claims. The
fix runs the other way: make the count an upper bound and let it go to zero.

**7. Replace `aggregate_confidence()` / `count_agreeing_analysts()` in `synthesis_lead.py:1368-1512`.**
These contain real defects — `aggregate_confidence`'s default weights sum to 1.00 but the `weights.get(
analyst, 0.2)` fallback breaks that for unknown analysts, and `_extract_bias` hardcodes VIX>25 as
bearish. But grepping the tree, neither function is called from either engine. They are dead code.
Deleting them is fine; fixing them is wasted effort.
