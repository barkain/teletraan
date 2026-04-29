# Teletraan v2 Alpha Engine Plan

Branch: `feature/v2-alpha-engine`

## Objective

Turn Teletraan from a prompt-heavy analysis app into a **ranked alpha discovery system**:

- **Daily, post-market pipeline** for a market-wide scan
- **Portfolio-aware, not portfolio-exclusive**
- **Structured factor model** that scores ideas before the LLM sees them
- **Richer data sources** for catalyst, flow, and fundamental edge
- **LLM as explainer / synthesizer**, not the primary scorer
- **Outcome feedback loop** that learns from realized results

The main output should be a **short, high-conviction list** of stocks, baskets, and relative-value trades with explicit evidence and expected horizon.

## Status

- ✓ Done Phase 1 — Foundation
  - ✓ Done analysis models and schemas
  - ✓ Done market-wide universe builder
  - ✓ Done market regime detection
  - ✓ Done daily scheduler wiring
- ✓ Done Phase 2 — Factor engine
  - ✓ Done deterministic scoring
  - ✓ Done portfolio-aware overlay
  - ✓ Done ranked candidate persistence

---

## Design Principles

1. **Score first, narrate second**
   - Deterministic factor engine produces candidate rankings.
   - LLM receives the ranked candidates and explains why they matter.

2. **Wide discovery, portfolio-aware overlay**
   - Full-market universe scan.
   - User holdings act as a context layer:
     - concentration risk
     - overlap with new ideas
     - hedge / trim / add context
   - Holdings do **not** restrict discovery to owned names.

3. **Catalyst-centric**
   - Alpha should be driven by a catalyst, a flow regime, or a mismatch between price and fundamentals.
   - Pure technical setups remain allowed, but only as one factor among many.

4. **Feedback-driven**
   - Every published insight becomes a labeled training / evaluation event.
   - We optimize for future hit rate and risk-adjusted return, not prose quality.

---

## Proposed Data Model

Create a new normalized analysis layer under `backend/models/` and `backend/schemas/` for factor scoring and outcomes.

### Core entities

#### `AnalysisRun`
One daily pipeline execution.

Fields:
- `id`
- `run_type` (`daily`, `on_demand`, `portfolio_refresh`)
- `started_at`, `completed_at`
- `market_date`
- `market_regime`
- `universe_size`
- `candidates_scored`
- `ideas_published`
- `status`
- `notes`

#### `MarketSnapshot`
Immutable market state at run time.

Fields:
- benchmark returns
- sector performance
- rates / yield curve
- VIX / volatility regime
- breadth / advance-decline
- major index trend state
- macro risk flags

#### `SecuritySignal`
Per-symbol factor inputs.

Fields:
- `symbol`
- `as_of_date`
- `price_momentum`
- `relative_strength`
- `trend_quality`
- `volume_confirmation`
- `earnings_revision_momentum`
- `fundamental_quality`
- `valuation_score`
- `sentiment_score`
- `options_flow_score`
- `short_squeeze_score`
- `insider_score`
- `institutional_flow_score`
- `macro_tailwind_score`
- `catalyst_score`
- `liquidity_score`
- `risk_score`
- `data_completeness`

#### `CandidateIdea`
The ranked output of the factor engine.

Fields:
- `symbol`
- `rank`
- `overall_score`
- `expected_horizon`
- `thesis_type` (`momentum`, `breakout`, `catalyst`, `value-reversion`, `pairs`, `hedge`)
- `bull_case`
- `bear_case`
- `key_drivers`
- `setup_trigger`
- `invalidations`
- `portfolio_relevance`
- `confidence`

#### `InsightOutcome`
Outcome labels for evaluation.

Fields:
- `candidate_id`
- `symbol`
- `horizon_days`
- `entry_price`
- `max_favorable_excursion`
- `max_adverse_excursion`
- `forward_return`
- `benchmark_relative_return`
- `hit_status`
- `time_to_hit`
- `time_to_invalid`
- `notes`

---

## Factor Model Design

The factor model should be explicit and auditable.

### 1. Regime filters
First determine the environment:
- risk-on / risk-off
- rates up / rates down
- volatility expansion / compression
- breadth expansion / narrowing
- sector rotation state

This determines which factors matter more.

### 2. Candidate scoring factors
Recommended factor groups:

#### Price / trend
- 20d / 50d / 200d trend
- relative strength vs SPY and sector ETF
- volatility-adjusted momentum
- breakout / base / squeeze quality
- volume confirmation

#### Fundamental quality
- revenue growth
- gross / operating margin trend
- FCF yield
- ROIC / ROE
- debt burden
- dilution / SBC trend
- balance-sheet resilience

#### Valuation / re-rating
- forward P/E vs sector
- EV/EBITDA vs sector
- PEG / growth-adjusted valuation
- valuation compression / expansion trend

#### Catalyst
- earnings date proximity
- guidance revision
- product launch
- regulatory event
- contract win / deal pipeline
- M&A / activist / insider event

#### Flow / positioning
- options unusual activity
- call/put imbalance
- IV skew and term structure
- short interest / borrow pressure
- institutional accumulation / 13F changes

#### Sentiment / narrative
- news sentiment change
- social sentiment acceleration
- analyst revisions / price targets
- thematic momentum

### 3. Scoring output
Produce:
- **overall alpha score**
- **subscores by factor family**
- **confidence / completeness penalty**
- **portfolio-aware relevance adjustment**

Important: missing data should reduce confidence, not silently default to neutral.

### 4. Ranking logic
The engine should:
- rank by expected return potential and catalyst strength
- penalize crowded/low-upside names unless flow confirms continuation
- boost under-covered names with strong fundamentals + improving revisions
- separate **long ideas**, **hedges**, and **pairs**

---

## New Data Sources

### A. SEC / filings
Use for durable signal:
- 13F institutional holdings changes
- Form 4 insider buys/sells
- 13D / 13G activism and ownership changes
- 8-K material events

Use cases:
- insider accumulation
- institutional sponsorship
- activist unlocks
- event-driven catalysts

### B. Options flow
Use for near-term repricing:
- unusual volume vs baseline
- open interest changes
- call/put ratio
- implied volatility vs realized volatility
- skew / term-structure shifts
- gamma-sensitive names

Use cases:
- event anticipation
- squeeze setups
- speculative conviction

### C. Short interest / borrow
Use for squeeze and crowding:
- short interest %
- days to cover
- borrow cost / utilization
- covering pressure

Use cases:
- short squeeze detection
- crowded short risk

### D. Fundamentals and revisions
Use for quality / re-rating:
- revenue, margin, FCF, ROIC
- earnings estimate revisions
- analyst target changes
- guidance deltas

Use cases:
- “cheap for a reason” filtering
- rerating candidates

### E. Macro / rates / positioning
Use for regime and factor rotation:
- yield curve
- real rates
- inflation surprises
- credit spreads
- volatility regime
- sector leadership

Use cases:
- sector tilts
- style tilts
- risk budget scaling

### F. Alternative data
Add only where it improves signal quality:
- web traffic / app downloads
- job postings
- shipment / logistics
- search trends
- store traffic / consumer demand proxies

Use cases:
- early fundamental inflection detection
- revenue surprise proxy

---

## Pipeline Stages

### Stage 0: Universe construction
Build a wide, liquid universe:
- large / mid / small cap eligible universe
- exclude illiquid, stale, and unsupported names
- sector coverage across the full market
- keep ETF and benchmark context

Outputs:
- eligible symbols
- liquidity filter
- sector / industry assignment
- portfolio holdings overlay

### Stage 1: Market regime detection
Compute:
- benchmark trend
- breadth
- volatility regime
- rate regime
- sector leadership

Output:
- regime labels
- factor weights for the rest of the run

### Stage 2: Structured factor ingestion
Fetch and normalize:
- price / volume
- fundamentals
- revisions
- options flow
- short interest
- SEC / insider / institutional
- sentiment
- macro context

Output:
- `SecuritySignal` rows per symbol

### Stage 3: Deterministic scoring
Compute:
- composite score
- subscores
- confidence
- data completeness
- setup type

Output:
- ranked candidate table
- top-N candidates by thesis type
- rejected / low-quality list for auditability

### Stage 4: Portfolio-aware overlay
Overlay current holdings:
- overlapping exposure
- concentration risk
- names to add / trim / hedge
- where existing holdings amplify or reduce risk

Output:
- portfolio action suggestions
- separate from market-wide discovery

### Stage 5: LLM synthesis
Feed only the top-ranked candidates plus portfolio overlay to the LLM.

The LLM should:
- explain the top ideas
- articulate bull / bear cases
- note missing data or uncertainty
- recommend catalysts to monitor
- produce a concise “why now” narrative

It should **not** invent the ranking.

### Stage 6: Publishing
Persist:
- ranked list
- explanations
- evidence snapshots
- intended horizon
- portfolio implications

### Stage 7: Outcome tracking
After horizon windows:
- measure return
- measure max drawdown / adverse excursion
- label hit / miss / early / late
- update factor weights and confidence calibration

---

## Daily Scheduler Setup

### Run timing
Recommended cadence:
- **daily post-market** run
- optional smaller pre-market refresh for major catalysts only

The post-market run is the canonical daily analysis because it captures:
- market close data
- earnings updates
- news / filing events from the day
- end-of-day option positioning where available

### Scheduler behavior
Add a scheduler job that:
1. Checks if the market day is complete
2. Builds the universe
3. Runs market regime detection
4. Runs factor scoring
5. Runs portfolio overlay
6. Runs LLM synthesis
7. Stores results and outcome-tracking seeds

### Failure handling
- If a data source fails, keep the run alive with partial data.
- If a critical source fails, mark confidence down and log the gap.
- Do not skip the run entirely unless the market snapshot is invalid.

### Idempotency
Daily runs should be safe to rerun for the same market date:
- unique run key = `run_type + market_date`
- existing rows should be updated, not duplicated

---

## Recommended Implementation Order

### Phase 1 — Foundation
1. ✓ Done Add new analysis models / schemas
2. ✓ Done Add the market-wide universe builder
3. ✓ Done Add market regime detection
4. ✓ Done Add daily scheduler wiring

### Phase 2 — Factor engine
5. ✓ Done Implement deterministic scoring
6. ✓ Done Add portfolio-aware overlay
7. ✓ Done Add candidate persistence

### Phase 3 — Data enrichment
8. Integrate SEC / insider / institutional sources
9. Integrate options flow / short interest
10. Add richer fundamentals and estimate revisions
11. Add any alt-data providers that are available and reliable

### Phase 4 — LLM synthesis
12. Refactor agent prompts so LLM explains ranked candidates
13. Make synthesis cite factor outputs and evidence
14. Separate market-wide ideas from portfolio-specific actions

### Phase 5 — Outcome loop
15. Persist outcomes
16. Score model performance by horizon and thesis type
17. Reweight factors / confidence from realized results

---

## Guardrails

- No single-source conviction.
- No holding-only discovery.
- No LLM-only ranking.
- No uncalibrated “strong buy” outputs without evidence.
- No silent fallback to weak data when stronger data is missing.
- No overfitting the system to mega-caps or already-owned names.

---

## Success Criteria

The v2 engine is successful if it:

- surfaces a smaller number of better ideas
- explains *why now* with concrete evidence
- identifies ideas outside the current portfolio
- separates genuine catalysts from noisy narratives
- improves hit rate and downside control over time
- can be evaluated objectively from outcome data
