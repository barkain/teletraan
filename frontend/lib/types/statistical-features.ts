/**
 * Statistical Features Types
 * Types for the statistical features API endpoints
 */

// Core feature type from the backend
export interface StatisticalFeature {
  id: string;
  symbol: string;
  feature_type: string;
  value: number;
  signal: string;
  percentile?: number;
  calculation_date: string;
  metadata?: Record<string, unknown>;
}

// Response type for getting features for a specific symbol
export interface StatisticalFeaturesResponse {
  symbol: string;
  features: StatisticalFeature[];
  calculation_date: string;
}

// Signal strength levels
export type SignalStrength = 'strong' | 'moderate' | 'weak';

// Active signal across the watchlist
export interface ActiveSignal {
  symbol: string;
  feature_type: string;
  signal: string;
  value: number;
  strength: SignalStrength;
}

// Response type for active signals endpoint
export interface ActiveSignalsResponse {
  signals: ActiveSignal[];
  count: number;
  as_of: string;
}

// Request parameters for filtering active signals
export interface ActiveSignalsParams {
  signal_type?: string;
  min_strength?: SignalStrength;
}

// Response type for compute features endpoint
export interface ComputeFeaturesResponse {
  status: string;
  message: string;
  symbols_processed?: string[];
  features_computed?: number;
}

// Request body for compute features
export interface ComputeFeaturesRequest {
  symbols?: string[];
}
