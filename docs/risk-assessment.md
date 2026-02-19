# Risk Assessment Pipeline

Risk assessment in Teletraan is executed by a dedicated **Risk Analyst** agent that runs as one of the five specialist analysts in both the `DeepAnalysisEngine` and `AutonomousDeepEngine` pipelines. A small set of algorithmic computations (historical volatility, max drawdown, ATR) are performed pre-LLM; everything else -- VaR, position sizing, tail risk, invalidation triggers -- is LLM-generated judgment.

---

## Pipeline Flow

```
                          Market Data (prices, indicators, VIX, portfolio)
                                            |
                                            v
                          +----------------------------------+
                          |  format_risk_context()           |
                          |  Pre-LLM algorithmic calcs:      |
                          |  - 20d historical volatility     |
                          |  - Max drawdown                  |
                          |  - ATR as % of price             |
                          |  - Bollinger width               |
                          |  - Bollinger-Keltner squeeze     |
                          |  - Volume/SMA classification     |
                          |  - Support/resistance levels     |
                          +----------------------------------+
                                            |
                                            v
                          +----------------------------------+
                          |  Risk Analyst LLM                |
                          |  (RISK_ANALYST_PROMPT)           |
                          |                                  |
                          |  Produces:                       |
                          |  - Volatility regime             |
                          |  - Per-symbol risk assessments   |
                          |  - Portfolio-level risks         |
                          |  - Tail risk events              |
                          +----------------------------------+
                                            |
                                            v
                          +----------------------------------+
                          |  parse_risk_response()           |
                          |  JSON extraction with fallbacks  |
                          +----------------------------------+
                                            |
                                            v
                +-----------------------------------------------+
                |  Synthesis Lead                               |
                |  - Receives risk report via _format_risk_report() |
                |  - Applies conflict resolution rules          |
                |  - Weights risk analyst at 20% in confidence  |
                |  - Emits risk_factors[] + invalidation_trigger|
                +-----------------------------------------------+
                                            |
                                            v
                +-----------------------------------------------+
                |  Storage                                      |
                |  - DeepInsight: risk_factors, invalidation,   |
                |    stop_loss, confidence                      |
                |  - InsightResearchContext: full risk_report    |
                +-----------------------------------------------+
                                            |
                                            v
                +-----------------------------------------------+
                |  Frontend                                     |
                |  - deep-insight-card.tsx: rose styling, icons |
                |  - insight-detail-view.tsx: RiskAssessmentSection |
                |    with risk level derivation + layman summary|
                +-----------------------------------------------+
```

---

## Pre-LLM Algorithmic Computations

Located in `format_risk_context()` (`backend/analysis/agents/risk_analyst.py`, lines 312-569):

| Computation | Method | Source |
|-------------|--------|--------|
| **20-day historical volatility** | Std dev of daily returns, annualized by sqrt(252) | Close prices |
| **Max drawdown** | Peak-to-trough over available price window | Close prices |
| **Support / resistance** | Min low and max high over 20-period window | OHLC prices |
| **ATR %** | ATR(14) / current price | Pre-computed indicator |
| **Bollinger Band width** | (upper - lower) / middle * 100 | Bollinger Bands |
| **Bollinger-Keltner squeeze** | Boolean: Bollinger bands inside Keltner channels | Bollinger + Keltner |
| **Volume classification** | Thresholds at 0.5/0.8/1.2/1.5/2.0 vs SMA | Volume data |

Additional context appended by `_format_volatility_context()` (lines 186-309): detects squeeze setups, formats VIX data, portfolio positions, sector correlations, economic indicators, prediction market probabilities, and Reddit sentiment.

---

## LLM Risk Analyst Agent

**File:** `backend/analysis/agents/risk_analyst.py`

The agent follows the standard Prompt/Parse pattern:

- **System prompt** (`RISK_ANALYST_PROMPT`, lines 12-98): Instructs the LLM to assess volatility regimes, downside scenarios, position sizing, invalidation triggers, and portfolio considerations. References ATR, Bollinger Band width, Keltner Channels, volume/SMA ratios, prediction market tail risk, and Reddit sentiment as contrarian signals.
- **Response parser** (`parse_risk_response`, lines 572-625): Extracts JSON with multiple fallback strategies -- direct parse, code fence extraction, pattern matching.
- **Typed parser** (`parse_to_result`, lines 628-683): Converts raw dict into `RiskAnalysisResult` dataclass.

### Key Output Dataclasses

| Dataclass | Fields | Description |
|-----------|--------|-------------|
| `VolatilityRegime` | current_vix, regime, term_structure, implication | Regime: low_vol / normal / elevated / crisis. Term structure: contango / backwardation / flat |
| `RiskAssessment` | symbol, current_price, downside_target, max_drawdown_pct, var_95_daily, risk_reward, position_size_suggestion, stop_loss, invalidation_trigger | Per-symbol assessment. VaR and position sizing are LLM-estimated, not model-derived |
| `TailRisk` | event, probability, impact | Impact: mild / moderate / severe / extreme |
| `RiskAnalysisResult` | volatility_regime, risk_assessments[], portfolio_risks[], tail_risks[], key_observations[], confidence | Top-level container for the full risk analysis |

---

## Synthesis Integration

**File:** `backend/analysis/agents/synthesis_lead.py`

The Synthesis Lead receives the Risk Analyst's output alongside four other analyst reports and applies the following rules:

### Confidence Aggregation

Risk analyst receives **20%** default weight (hardcoded in `aggregate_confidence()`, lines 1211-1249):

| Analyst | Weight |
|---------|--------|
| Technical | 25% |
| Macro | 20% |
| **Risk** | **20%** |
| Sector | 20% |
| Correlation | 15% |

### Conflict Resolution

- Risk warnings **override** bullish signals if tail risk probability > 15% (prompt line 235)
- `_extract_bias()` for risk (lines 1329-1338): elevated/crisis VIX regime or VIX > 25 = bearish; low_vol and VIX < 15 = bullish

### Post-Synthesis Confidence Adjustment

`ConfidenceAdjuster` (`backend/analysis/confidence_adjuster.py`) calibrates final confidence using historical accuracy:

```
adjusted = (base * 0.7) + (historical * 0.3) + pattern_boost
```

- Clamped to [0.1, 0.95]
- Pattern boost up to 20% for patterns with > 60% success rate
- Requires sufficient `InsightOutcome` records to be effective

---

## Data Model

### Persisted Fields

**DeepInsight** (`backend/models/deep_insight.py`):

| Field | Type | Description |
|-------|------|-------------|
| `insight_type` | `String(50)` | Can be `"risk"` (one of 6 `InsightType` values) |
| `risk_factors` | `JSON (list[str])` | Risk factor strings, e.g. `["Earnings season volatility"]` |
| `invalidation_trigger` | `Text` | Condition that invalidates the thesis |
| `stop_loss` | `String(50)` | Stop-loss level, e.g. `"$142 (-5%)"` |
| `confidence` | `Float` | 0.0-1.0, influenced by risk assessment |

**InsightResearchContext** (`backend/models/insight_research_context.py`):

| Field | Type | Description |
|-------|------|-------------|
| `risk_report` | `JSON` | Full Risk Analyst output: volatility_regime, risk_assessments[], portfolio_risks[], tail_risks[] |

### In-Memory Dataclasses

**MacroScanResult** (`backend/analysis/agents/macro_scanner.py`):

| Field | Type | Description |
|-------|------|-------------|
| `market_regime` | `str` | "Risk-On", "Risk-Off", "Transitional", "Range-Bound" |
| `key_risks` | `list[MacroRisk]` | Each: description, probability, impact |
| `actionable_implications.risk_posture` | `str` | "defensive", "neutral", "aggressive" |

**OpportunityCandidate** (`backend/analysis/agents/opportunity_hunter.py`):

| Field | Type | Description |
|-------|------|-------------|
| `risk_level` | `str` | "low", "medium", "high" per candidate (LLM-assigned) |

### Schema & Report Fields

- `DeepInsightSchema` (`backend/schemas/deep_insight.py`): `risk_factors: list[str]`, `invalidation_trigger: Optional[str]`, `stop_loss: Optional[str]`
- `ReportInsight` (`backend/schemas/report.py`): `risk_factors: list[str]`, `stop_loss: Optional[str]`, `invalidation_trigger: Optional[str]`
- `DeepInsightType` (`frontend/types/index.ts`): includes `'risk'` as a valid type; `risk_factors: string[]` on the insight interface

---

## Frontend Display

### Insight Cards (`frontend/components/insights/deep-insight-card.tsx`)

- Risk `insight_type` gets rose-colored styling
- `risk_factors` rendered with `AlertTriangle` icons

### Insight Detail View (`frontend/components/insights/insight-detail-view.tsx`)

The `RiskAssessmentSection` component (lines 1642-1675):

| Logic | Rule |
|-------|------|
| Risk level derivation | >= 4 risk factors = "high", >= 2 = "moderate", else "low" |
| Layman summary | `"Risk level is {level}. Biggest concern: {risk_factors[0]}"` |
| Invalidation trigger | Rendered below risk factors |
| Macro regime badge | Risk-On = green, Risk-Off = red |
| Recession probability | Displayed with contextual interpretation |
| Evidence grouping | Aggregated from the risk analyst dimension |

---

## Known Gaps and Limitations

1. **No algorithmic VaR** -- The `var_95_daily` field in `RiskAssessment` is LLM-estimated, not computed from a parametric or Monte Carlo model.
2. **No historical backtesting** -- Risk assessments are not validated against historical data at generation time. `ConfidenceAdjuster` only calibrates post-hoc if sufficient `InsightOutcome` records exist.
3. **No real-time risk monitoring** -- Risk is assessed at analysis time only. No continuous monitoring, no stop-loss alerts, no portfolio risk dashboard.
4. **No options data** -- Implied volatility is referenced in prompts but not sourced from options chains. The risk analyst operates on historical price data only.
5. **No correlation matrix** -- Portfolio correlation risk is qualitatively assessed by the LLM, not computed from a covariance matrix.
6. **Fixed synthesis weight** -- The 20% weight for the risk analyst in `aggregate_confidence()` is hardcoded, not adaptive to market conditions.
7. **LLM-assigned opportunity risk** -- The `risk_level` field on `OpportunityCandidate` is the LLM's judgment, not derived from a quantitative model.

---

## File Reference

| File | Risk-Related Content |
|------|---------------------|
| `backend/analysis/agents/risk_analyst.py` | Primary risk agent: prompt, dataclasses, context formatter, parser |
| `backend/analysis/agents/synthesis_lead.py` | Risk report formatting, conflict resolution, confidence aggregation |
| `backend/analysis/agents/macro_scanner.py` | MacroRisk dataclass, risk_posture, market_regime |
| `backend/analysis/agents/opportunity_hunter.py` | OpportunityCandidate.risk_level |
| `backend/analysis/deep_engine.py` | Orchestrates Risk Analyst as 1 of 5 parallel agents |
| `backend/analysis/autonomous_engine.py` | Risk Analyst as 1 of 3 core deep-dive agents |
| `backend/analysis/confidence_adjuster.py` | Historical accuracy-based confidence calibration |
| `backend/models/deep_insight.py` | risk_factors, invalidation_trigger, stop_loss columns |
| `backend/models/insight_research_context.py` | risk_report JSON column |
| `backend/schemas/deep_insight.py` | risk_factors, invalidation_trigger Pydantic fields |
| `backend/schemas/report.py` | risk_factors, stop_loss, invalidation_trigger |
| `frontend/types/index.ts` | DeepInsightType includes 'risk', risk_factors field |
| `frontend/components/insights/deep-insight-card.tsx` | Risk styling, risk_factors rendering |
| `frontend/components/insights/insight-detail-view.tsx` | RiskAssessmentSection component, risk level derivation |
