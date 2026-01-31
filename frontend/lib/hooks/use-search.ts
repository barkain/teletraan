'use client';

import { useQuery } from '@tanstack/react-query';
import { useState, useCallback, useMemo } from 'react';
import { fetchApi } from '@/lib/api';
import type { Stock, Insight } from '@/types';

// Search result types
export interface StockSearchResult extends Stock {
  relevance_score: number;
}

export interface InsightSearchResult extends Insight {
  relevance_score: number;
}

export interface GlobalSearchResponse {
  stocks: StockSearchResult[];
  insights: InsightSearchResult[];
  total: number;
  query: string;
}

export interface StockSearchResponse {
  stocks: StockSearchResult[];
  total: number;
  query: string;
}

export interface InsightSearchResponse {
  insights: InsightSearchResult[];
  total: number;
  query: string;
}

export interface SearchSuggestion {
  text: string;
  type: 'stock' | 'insight';
  symbol?: string;
  id?: number;
}

// Debounce helper
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useMemo(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => {
      clearTimeout(handler);
    };
  }, [value, delay]);

  return debouncedValue;
}

// Global search hook
export function useGlobalSearch(query: string, options?: { enabled?: boolean }) {
  const debouncedQuery = useDebounce(query, 300);
  const enabled = (options?.enabled ?? true) && debouncedQuery.length >= 1;

  return useQuery<GlobalSearchResponse>({
    queryKey: ['global-search', debouncedQuery],
    queryFn: () =>
      fetchApi<GlobalSearchResponse>(
        `/api/search?q=${encodeURIComponent(debouncedQuery)}`
      ),
    enabled,
    staleTime: 30 * 1000, // 30 seconds
  });
}

// Stock search hook
export function useStockSearch(
  query: string,
  options?: {
    enabled?: boolean;
    sector?: string;
    activeOnly?: boolean;
    limit?: number;
  }
) {
  const debouncedQuery = useDebounce(query, 300);
  const enabled = (options?.enabled ?? true) && debouncedQuery.length >= 1;

  const params = new URLSearchParams();
  params.set('q', debouncedQuery);
  if (options?.sector) params.set('sector', options.sector);
  if (options?.activeOnly !== undefined)
    params.set('active_only', String(options.activeOnly));
  if (options?.limit) params.set('limit', String(options.limit));

  return useQuery<StockSearchResponse>({
    queryKey: ['stock-search', debouncedQuery, options?.sector, options?.limit],
    queryFn: () =>
      fetchApi<StockSearchResponse>(`/api/search/stocks?${params.toString()}`),
    enabled,
    staleTime: 30 * 1000,
  });
}

// Insight search hook
export function useInsightSearch(
  query: string,
  options?: {
    enabled?: boolean;
    insightType?: string;
    severity?: string;
    activeOnly?: boolean;
    limit?: number;
  }
) {
  const debouncedQuery = useDebounce(query, 300);
  const enabled = (options?.enabled ?? true) && debouncedQuery.length >= 1;

  const params = new URLSearchParams();
  params.set('q', debouncedQuery);
  if (options?.insightType) params.set('insight_type', options.insightType);
  if (options?.severity) params.set('severity', options.severity);
  if (options?.activeOnly !== undefined)
    params.set('active_only', String(options.activeOnly));
  if (options?.limit) params.set('limit', String(options.limit));

  return useQuery<InsightSearchResponse>({
    queryKey: [
      'insight-search',
      debouncedQuery,
      options?.insightType,
      options?.severity,
      options?.limit,
    ],
    queryFn: () =>
      fetchApi<InsightSearchResponse>(`/api/search/insights?${params.toString()}`),
    enabled,
    staleTime: 30 * 1000,
  });
}

// Search suggestions hook for autocomplete
export function useSearchSuggestions(
  query: string,
  options?: { enabled?: boolean; limit?: number }
) {
  const debouncedQuery = useDebounce(query, 200);
  const enabled = (options?.enabled ?? true) && debouncedQuery.length >= 1;

  const params = new URLSearchParams();
  params.set('q', debouncedQuery);
  if (options?.limit) params.set('limit', String(options.limit));

  return useQuery<{ suggestions: SearchSuggestion[] }>({
    queryKey: ['search-suggestions', debouncedQuery],
    queryFn: () =>
      fetchApi<{ suggestions: SearchSuggestion[] }>(
        `/api/search/suggestions?${params.toString()}`
      ),
    enabled,
    staleTime: 30 * 1000,
  });
}

// Combined search state hook for managing search UI
export function useSearchState() {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');

  const open = useCallback(() => setIsOpen(true), []);
  const close = useCallback(() => {
    setIsOpen(false);
    setQuery('');
  }, []);
  const toggle = useCallback(() => setIsOpen((prev) => !prev), []);

  const clearQuery = useCallback(() => setQuery(''), []);

  return {
    isOpen,
    query,
    setQuery,
    open,
    close,
    toggle,
    clearQuery,
  };
}
