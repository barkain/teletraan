/**
 * Track Record Types
 * Types for insight outcome tracking and performance metrics
 */

// Outcome categories for validated insights
export type OutcomeCategory =
  | 'STRONG_SUCCESS'
  | 'SUCCESS'
  | 'PARTIAL_SUCCESS'
  | 'NEUTRAL'
  | 'PARTIAL_FAILURE'
  | 'FAILURE'
  | 'STRONG_FAILURE';

// Tracking status for insight outcomes
export type TrackingStatus =
  | 'PENDING'
  | 'TRACKING'
  | 'COMPLETED'
  | 'INVALIDATED';

// Individual insight outcome
export interface InsightOutcome {
  id: string;
  insight_id: string;
  tracking_status: TrackingStatus;
  tracking_start_date: string;
  tracking_end_date: string;
  initial_price: number;
  current_price?: number;
  final_price?: number;
  actual_return_pct?: number;
  predicted_direction: string;
  thesis_validated?: boolean;
  outcome_category?: OutcomeCategory;
  validation_notes?: string;
  days_remaining?: number;
}

// Track record statistics from knowledge API
export interface TrackRecordStats {
  total_insights: number;
  successful: number;
  success_rate: number;
  by_type: Record<string, { total: number; successful: number; success_rate: number; avg_return?: number | null }>;
  by_action: Record<string, { total: number; successful: number; success_rate: number; avg_return?: number | null }>;
  avg_return_successful: number;
  avg_return_failed: number;
}

// Outcome summary statistics from outcomes API
export interface OutcomeSummary {
  total_tracked: number;
  currently_tracking: number;
  completed: number;
  success_rate: number;
  avg_return_when_correct: number;
  avg_return_when_wrong: number;
  by_direction: Record<string, {
    total: number;
    correct: number;
    avg_return: number;
  }>;
  by_category: Record<OutcomeCategory, number>;
}

// Outcomes list response
export interface OutcomesListResponse {
  items: InsightOutcome[];
  total: number;
}

// Track record list params
export interface TrackRecordParams {
  insight_type?: string;
  action_type?: string;
  lookback_days?: number;
}

// Outcomes list params
export interface OutcomesListParams {
  status?: TrackingStatus;
  validated?: boolean;
  limit?: number;
  offset?: number;
}

// Monthly trend data
export interface MonthlyTrendData {
  month: string;
  rate: number;
  total?: number;
  successful?: number;
}

// Monthly trend response
export interface MonthlyTrendResponse {
  data: MonthlyTrendData[];
  period_months: number;
}
