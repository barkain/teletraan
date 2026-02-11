/**
 * Knowledge Types
 * Types for the knowledge patterns and conversation themes API endpoints
 */

// Pattern types for validated market patterns
export type PatternType =
  | 'TECHNICAL_SETUP'
  | 'MACRO_CORRELATION'
  | 'SECTOR_ROTATION'
  | 'EARNINGS_PATTERN'
  | 'SEASONALITY'
  | 'CROSS_ASSET';

// Knowledge pattern - validated recurring market pattern
export interface KnowledgePattern {
  id: string;
  pattern_name: string;
  pattern_type: PatternType;
  description: string;
  trigger_conditions: Record<string, unknown>;
  expected_outcome: string;
  success_rate: number;
  occurrences: number;
  successful_outcomes: number;
  avg_return_when_triggered?: number;
  lifecycle_status?: string | null;
  related_symbols?: string[] | null;
  related_sectors?: string[] | null;
  extraction_source?: string | null;
  last_evaluated_at?: string | null;
  is_active: boolean;
  last_triggered_at?: string;
  created_at?: string;
  updated_at?: string;
}

// Response type for pattern list endpoint
export interface KnowledgePatternsResponse {
  items: KnowledgePattern[];
  total: number;
}

// Request parameters for filtering patterns
export interface KnowledgePatternsParams {
  pattern_type?: PatternType;
  min_success_rate?: number;
  is_active?: boolean;
  limit?: number;
  offset?: number;
}

// Summary statistics for patterns
export interface PatternsSummary {
  total: number;
  active: number;
  avg_success_rate: number;
  by_type: Record<string, number>;
  by_lifecycle: Record<string, number>;
  top_symbols: string[];
  top_sectors: string[];
}

// Request parameters for matching patterns
export interface MatchingPatternsParams {
  symbols?: string[];
  current_rsi?: number;
  current_vix?: number;
}

// Theme types for conversation themes
export type ThemeType =
  | 'MARKET_REGIME'
  | 'SECTOR_TREND'
  | 'MACRO_THEME'
  | 'FACTOR_ROTATION'
  | 'RISK_CONCERN'
  | 'OPPORTUNITY_THESIS';

// Conversation theme - recurring topic from user conversations
export interface ConversationTheme {
  id: string;
  theme_name: string;
  theme_type: ThemeType;
  description: string;
  keywords: string[];
  related_symbols: string[];
  related_sectors: string[];
  mention_count: number;
  current_relevance: number;
  first_mentioned_at: string;
  last_mentioned_at: string;
  created_at?: string;
  updated_at?: string;
}

// Response type for themes list endpoint
export interface ConversationThemesResponse {
  items: ConversationTheme[];
  total: number;
}

// Request parameters for filtering themes
export interface ConversationThemesParams {
  theme_type?: ThemeType;
  min_relevance?: number;
  sector?: string;
  limit?: number;
  offset?: number;
}
