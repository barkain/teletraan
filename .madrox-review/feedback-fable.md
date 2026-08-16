# Teletraan Feedback-Loop Audit — why recommendations don't improve

Reviewer: Fable (independent reviewer 1 of 3) · Branch: `feat/news-sentiment` · DB snapshot: `backend/data/teletraan.db` (last write 2026-06-24)

## Verdict in one paragraph

The learning loop **is mechanically wired** — patterns and track record are injected into the synthesis prompt (`deep_engine.py:530-545`, `autonomous_engine.py:2400-2435`) and a `ConfidenceAdjuster` rewrites confidence post-synthesis. The reason recommendations never improve is that **everything flowing through that loop is fabricated or corrupted**: (1) the outcome ground truth is wrong — a flat ±1% absolute move over a fixed 20 days, evaluated on average **31 days late**, with no benchmark, no target/stop, and a price-history bug that means intraperiod data is never recorded; (2) pattern "success rates" are the extraction LLM's own confidence guess, never validated — 184 of the 190 patterns that pass the "validated pattern" prompt filter have **zero** validated outcomes; (3) the one pattern that *was* validated got double-counted 22 times by a re-processing bug and now claims "96% over 23 occurrences." Garbage in the loop means the loop, though closed, teaches nothing. Actual hit rate: **32/154 = 20.8%**, with bearish calls at **2/41 = 4.9%** while the shorted names rose +16% on average.

---

## TOP 5 CONCRETE CHANGES (ranked by expected impact)

### 1. Rebuild the outcome success criterion: benchmark-relative, horizon-matched, evaluated at the actual window end

**Defects (all in `backend/analysis/outcome_tracker.py`):**
- `_evaluate_outcome`, lines 224-229: bullish = "validated" if raw return > +1%, bearish if < −1%. No benchmark. SPY rose **+6.6%** over the tracked period (692.12 → 737.55, DB `price_history`), so a bullish call that *underperformed the index by 5pp* still counts as a win, and any bearish call in an up-market is near-auto-fail. The system's bullish calls averaged +1.67% in a +6.6% market — **negative alpha scored as 30% "success."**
- `_evaluate_outcome`, line 207: `final_price = current_price` — the price at whatever moment `check_outcomes()` happened to run, not the price at `tracking_end_date`. DB proof: completed outcomes were evaluated on average **30.9 days after** the window closed (avg of `julianday(updated_at) − julianday(tracking_end_date)`). A "20-day" prediction is actually scored on ~51 days of drift.
- `deep_engine.py:1104` and `autonomous_engine.py:2969,4220`: `tracking_days=20` hardcoded for every insight, ignoring `DeepInsight.time_horizon`. A "3-6 months" thesis is judged after one month; `_HORIZON_DAYS` (outcome_tracker.py:24-30) exists but is only used for staleness, not tracking length.
- `models/insight_outcome.py:122`: `price_history` is a plain `JSON` column (no `MutableList`), and `check_outcomes` mutates it in place (`outcome.price_history.append(...)`, line 174) — the change is never marked dirty. DB proof: **all 221 outcomes have exactly 1 price_history entry.** Consequently `max_favorable_move`/`max_adverse_move`/checkpoints are meaningless, and target/stop triggers fire only if the app happened to be running that day.
- `check_price_level_triggers` parses `entry_zone`/`target_price`/`stop_loss` but `_evaluate_outcome` never uses them — the insight's own stated targets play no role in whether it "worked."

**The change:** at evaluation time, fetch the daily close series for `[start, end]` from yfinance (or the existing `price_history` table) instead of polling live prices. Score: (a) return measured exactly at `tracking_end_date`; (b) `alpha = symbol_return − SPY_return` over the same window; validated ⇔ alpha in predicted direction beyond a threshold (e.g. ±2%), or target hit before stop; (c) tracking window derived from `time_horizon` via `_HORIZON_DAYS`. This also fixes the 61 stale outcomes (see PROOF): a historical-fetch evaluator can resolve any window retroactively, so it no longer matters that the scheduler only runs while the app is up. Re-run it over all 154 completed outcomes to rebuild an honest track record.

**Measure:** re-scored hit rate and average alpha per call, by direction/action. Everything downstream (patterns, confidence, prompt context) is only as good as this label.

### 2. Stop injecting fabricated pattern statistics into the synthesis prompt

**Defects:**
- `pattern_extractor.py:691`: `success_rate=float(pattern_data.get("confidence", ...))` — a brand-new, never-tested pattern is born with a "success rate" equal to the LLM's guess (typically 0.6-0.9).
- `memory_service.py:103-111` (`get_relevant_patterns`): filters `success_rate >= 0.5` and `is_active` only — no check of `successful_outcomes`, `occurrences`, or `lifecycle_status`. DB proof: **190/229 patterns pass this filter; 184 of them have `successful_outcomes = 0`.** All 229 patterns are `lifecycle_status='draft'`. These reach the prompt as "**Success Rate: 70% over 1 occurrences**" (`synthesis_lead.py:1243`) under the heading of validated patterns, and the synthesis lead is explicitly told to weigh them.
- `outcome_tracker.py:update_pattern_success_rates` (lines 271-318): every invocation re-iterates **all** COMPLETED outcomes and calls `record_occurrence` again — there is no "already counted" marker. It runs 3×/day from the scheduler (`scheduler/etl.py:846-863`). DB proof: the top patterns all sit at exactly `occurrences=23`, including "False Rotation Volume-Price Divergence" at **23 occurrences / 22 successes / 96%** — one real outcome counted 22 times. That pattern now clears every quality bar in `ConfidenceAdjuster.calculate_pattern_boost` and the prompt filter.
- `pattern_extractor.py:399` `validate_pattern_quality` — the only statistical bar in the codebase (needs ≥2 occurrences etc.) — is **dead code**: zero call sites.
- `memory_service.get_relevant_patterns` accepts `symbols` and never uses it (only logged) — patterns about LatAm banks can match an NVDA run.

**The change:** (a) new patterns get `success_rate=0.5, occurrences=0` and stay `draft`; store LLM confidence in a separate `extraction_confidence` field if you want it. (b) `update_pattern_success_rates` processes each (outcome, pattern) pair once — add `patterns_scored_at` on `InsightOutcome` or a join table. (c) Promote `draft → active` only when `occurrences ≥ 5` and the Wilson lower bound of `successful_outcomes/occurrences` > 0.5; `get_relevant_patterns` filters on `lifecycle_status='active'` and ranks by Wilson LB, and intersects `related_symbols`/`related_sectors` with the run's symbols. Wire or delete `validate_pattern_quality`. (d) One-off data repair: reset all pattern counters and replay the (fixed) outcomes once.

**Measure:** count of patterns reaching prompts with zero validated outcomes (must be 0); hit rate of insights generated with pattern context vs without.

### 3. Feed the model its *failures*, not just an aggregate number — and make what it learns change candidate selection

**Defect:** the only learning that reaches the next run's prompt is `build_track_record_context` (`synthesis_lead.py:1266-1315`) — aggregate percentages by type/action — plus a confidence rescale in `ConfidenceAdjuster.adjust_confidence` (`confidence_adjuster.py:162-165`: `0.6·base + 0.2·historical`, clamped to ≥0.1). With a 20.8% overall record this mostly performs uniform shrinkage of every confidence toward ~0.5, which the frontend then renders — no change to *which symbols get picked or what theses get written*. Nothing tells the synthesizer **what** it got wrong: it has produced 41 bearish calls with 2 wins while the shorted names averaged +16%, and the next run's prompt contains no trace of any specific failed thesis. The insight-selection phases (MacroScanner → OpportunityHunter → DeepDive) consume no outcome data at all.

**The change:** build a "post-mortem context" block injected alongside the track record: the 5 most recent STRONG_FAILURE/FAILURE outcomes with symbol, action, stated thesis (first ~200 chars), predicted vs actual (benchmark-relative) return, and the by-action hit table with explicit guidance rendered from data (e.g. "bearish single-name calls: 2/41 — require extraordinary evidence, or express as reduced sizing instead of SELL"). Inject a compact version into the *OpportunityHunter/DeepDive* prompts too, so learning shifts candidate selection, not just the confidence decimal. This is ~1 query + ~40 lines of formatting; all data already exists.

**Measure:** next-30-outcome benchmark-relative hit rate by action; specifically watch whether bearish-call frequency and bearish hit rate move.

### 4. Build the minimum viable evaluation harness (there is none for the insight pipeline)

**Defect:** `analysis/backtester.py` computes ICs for the *alpha engine's technical factors* only (and its calibration JSONs, dated May 7, do feed `alpha_synthesis.py`). The LLM insight pipeline — the thing that produces user-facing recommendations — has **no backtest, no holdout, no way to tell whether any prompt/pipeline change made recommendations better or worse**. The 20.8% number was computed for this review by hand; no endpoint or job reports benchmark-adjusted performance, and nothing snapshots performance per system version.

**The change (concretely, with existing data):** a deterministic script/job `eval_insights.py` that: (1) takes every `DeepInsight` with a directional action and `created_at` older than its horizon; (2) computes horizon returns for symbol and SPY from the local `price_history` table (already populated daily by ETL; backfill script exists); (3) emits per-cohort metrics: **benchmark-adjusted hit rate, mean alpha per call, and a confidence-decile calibration curve (ECE)**, keyed by month and by a `pipeline_version` tag you stamp onto `DeepInsight.discovery_context` at generation time. Store each eval run as a JSON snapshot (like `backtest_calibration.json`). That gives an A/B answer for every future change — including changes #1-#3 above — at zero LLM cost. ~1 day of work; no new data sources.

**Measure:** the harness *is* the measure. Acceptance: two consecutive eval snapshots comparable across a deliberate prompt change.

### 5. Make every directional insight carry a falsifiable trade spec, and score against it

**Defect:** `DeepInsight` has `entry_zone`, `target_price`, `stop_loss` as free-text `VARCHAR(50)` (`models/deep_insight.py`), no position-size field exists anywhere, and the synthesis parser accepts insights without them. DB proof: only **105/414 (25%)** insights have entry/target/stop; the other 75% are a direction and a paragraph. The frontend (`insight-detail-view.tsx:1110-1130`) renders these fields only when present, so most insights display as un-actionable narrative. And per finding #1, even when targets exist they don't affect validation.

**The change:** (a) in `parse_synthesis_response` / the synthesis prompt contract, make `entry_zone`, `target_price`, `stop_loss`, `time_horizon` **required** for BUY/STRONG_BUY/SELL/STRONG_SELL — one repair round-trip to the LLM if missing, else downgrade the action to WATCH; (b) store them as numeric low/high columns (the regex parser `_parse_price_range` already exists at `outcome_tracker.py:552`); (c) add `suggested_size_pct` derived from confidence × distance-to-stop (risk-normalized), so two 0.8-confidence ideas with 5% vs 25% stops aren't presented identically; (d) feed target/stop into the outcome evaluator (change #1): target-before-stop = success regardless of the ±% bands.

**Measure:** fraction of directional insights with complete trade specs (target 100%); then reward/risk realized vs stated on resolved outcomes.

---

## PROOF (real numbers from `backend/data/teletraan.db`, read-only, 2026-08-08)

- **414** `deep_insights` (2026-02-01 → 2026-06-24); **221** have an `insight_outcomes` row (the 193 untracked are mostly HOLD=135 and WATCH=34 — reasonable, they're unfalsifiable as tracked).
- Outcomes: **154 COMPLETED, 67 TRACKING** — and **61 of the 67 "TRACKING" rows are past their `tracking_end_date`** and will never resolve unless the app is running when a scheduler slot fires (jobs at 9:30/13:30/16:30 ET; a dev app that's rarely up then evaluates late or never — completed rows averaged **30.9 days late**).
- **Hit rate: 32/154 = 20.8%** (`thesis_validated=1`), and even that is against the trivial ±1%-absolute bar. Category spread: 33 STRONG_FAILURE, 36 FAILURE, 28 PARTIAL_FAILURE, 15 NEUTRAL, 21 PARTIAL_SUCCESS, 8 SUCCESS, 13 STRONG_SUCCESS.
- By direction (completed): bullish **27/89** (avg raw return **+1.67%** while SPY did **+6.6%** over the same span → negative alpha), bearish **2/41** (avg **+16.0%** — the shorted names ripped), neutral 3/24. By action: BUY 23/62, STRONG_BUY 4/27, SELL **1/29**, STRONG_SELL 1/12, WATCH 2/18, HOLD 1/6.
- Patterns: **229 total, all `lifecycle_status='draft'`**. **190** pass the `success_rate ≥ 0.5` filter used by `get_relevant_patterns` (i.e., get presented to the synthesis LLM as validated patterns); **184 of those 190 have `successful_outcomes = 0`** — their "success rate" is the extraction LLM's confidence, never tested. Only **6** patterns have any validated success; only 32 have `occurrences ≥ 2`.
- Double-counting: 8+ patterns sit at exactly `occurrences=23` (e.g. "Real Rate Decline Gold Rally": 23/0, 0%; "False Rotation Volume-Price Divergence": **23 occurrences, 22 successes, 96%** — a single outcome re-counted on every scheduler pass).
- `price_history` on outcomes: **all 221 rows have exactly 1 entry** (the initial price) — the in-place JSON append in `check_outcomes` never persists.
- Trade specs: **105/414 (25.4%)** insights have entry/target/stop; `position_size` column does not exist.
- Confidence: 107 insights at 0.8, 84 at 0.7 — vs a realized 20.8% hit rate. Massive overconfidence; no calibration mechanism has valid data to correct it.
- **Answer to the critical question:** learned data *does* flow back into prompts (pattern context + track record in `SYNTHESIS_LEAD_PROMPT` placeholders; `ConfidenceAdjuster` rewrites stored confidence). The loop is closed in code and open in substance: what flows back is unvalidated (184/190 patterns), corrupted (double-counting), or too coarse to act on (aggregate percentages, uniform confidence shrinkage). Nothing learned ever influences symbol/candidate selection.
- **Track-record honesty:** the `/knowledge/track-record` and monthly-trend endpoints include failures and are arithmetically honest, but the denominator silently excludes the 61 stuck-in-TRACKING outcomes (28% of directional calls) and any insight whose initial price fetch failed (`start_tracking` raises → skipped, `deep_engine.py:1112`). The monthly trend buckets by `tracking_end_date` while evaluation happens ~31 days later, so recent months systematically show fewer (and different) outcomes than actually resolved. Not cooked — but incomplete and time-smeared.

## REJECTED (plausible ideas not worth doing now)

1. **FEEDBACK_LOOP_DESIGN.md Phase 2 (logistic regression over 9 factor scores per regime).** With ~154 resolved outcomes total — none linked to `candidate_ideas` (the FK doesn't exist yet), split across regimes — a 9-coefficient logistic fit per regime is guaranteed overfitting on labels that are themselves wrong (see #1). Do design-doc Phase 1 (the FK, cheap) and revisit after ≥200 *correctly-labeled* outcomes per regime. Building it now would launder noise into "learned weights."
2. **Platt scaling / ECE-based confidence calibration (design-doc Phase 4).** Same reason: calibrating against broken labels calibrates to garbage. The calibration *curve* belongs in the eval harness (#4) as a diagnostic first.
3. **Embedding-based pattern similarity / better pattern merging.** The Jaccard merger is crude, but dedup quality is irrelevant while pattern statistics are fabricated. Fix validation (#2); most of the 229 drafts should simply be culled.
4. **More data sources / more analyst agents.** Synthesis context is already hard-truncated (`deep_engine.py:508-524`: 2,000 chars per analyst, 12,000 total) — adding inputs feeds the truncator, not the model. If anything, *raise* the caps before adding sources; but neither addresses the missing feedback substance.
5. **Real-time/intraday outcome polling infrastructure.** Tempting given the stale-tracking problem, but unnecessary: historical daily closes fetched at evaluation time (#1) resolve any window retroactively with zero always-on requirements. Building a daemon to keep the current live-polling design alive would be fixing the wrong layer.
6. **UI for pattern review/curation.** Human-in-the-loop curation of 229 draft patterns is busywork; after #2, the surviving set will be small and self-maintaining.
