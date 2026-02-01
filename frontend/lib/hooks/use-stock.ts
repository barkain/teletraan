'use client';

import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { toast } from 'sonner';
import { useEffect } from 'react';
import type { Stock, PriceHistory, Insight, PaginatedResponse } from '@/types';

/**
 * Custom hook for fetching stock details
 * Uses the v1 stocks API
 */
export function useStock(symbol: string | undefined) {
  const query = useQuery<Stock>({
    queryKey: ['stock', symbol],
    queryFn: () => api.stocks.get(symbol!),
    enabled: !!symbol,
    staleTime: 30 * 1000, // 30 seconds
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
  });

  useEffect(() => {
    if (query.error) {
      toast.error(`Failed to fetch stock data for ${symbol}`, {
        description: query.error instanceof ApiError
          ? `Server error: ${query.error.status}`
          : 'Please try again later.',
      });
    }
  }, [query.error, symbol]);

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && !query.data,
  };
}

/**
 * Custom hook for fetching stock price history
 * Uses the v1 stocks/{symbol}/history API
 */
export function useStockPriceHistory(
  symbol: string | undefined,
  days: number = 30
) {
  const query = useQuery<PriceHistory[]>({
    queryKey: ['stock-price-history', symbol, days],
    queryFn: () => api.stocks.history(symbol!, { days }),
    enabled: !!symbol,
    staleTime: 60 * 1000, // 1 minute
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
  });

  useEffect(() => {
    if (query.error) {
      toast.error(`Failed to fetch price history for ${symbol}`, {
        description: 'Historical data may be unavailable.',
      });
    }
  }, [query.error, symbol]);

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (!query.data || query.data.length === 0),
  };
}

/**
 * Custom hook for fetching all stocks
 * Uses the v1 stocks API with pagination
 */
export function useStocks(params?: { sector?: string; limit?: number }) {
  const query = useQuery<Stock[]>({
    queryKey: ['stocks', params?.sector, params?.limit],
    queryFn: async () => {
      const response = await api.stocks.list({
        sector: params?.sector,
        limit: params?.limit ?? 100,
      });
      return response.items;
    },
    staleTime: 30 * 1000, // 30 seconds
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
  });

  useEffect(() => {
    if (query.error) {
      toast.error('Failed to fetch stocks list', {
        description: 'Please check your connection and try again.',
      });
    }
  }, [query.error]);

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (!query.data || query.data.length === 0),
  };
}

/**
 * Custom hook for fetching insights related to a stock
 * Uses the v1 insights API with symbol filter
 */
export function useStockInsights(symbol: string | undefined) {
  const query = useQuery<Insight[]>({
    queryKey: ['stock-insights', symbol],
    queryFn: async () => {
      const response = await api.insights.list({ symbol, per_page: 10 });
      return response.items;
    },
    enabled: !!symbol,
    staleTime: 60 * 1000, // 1 minute
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
  });

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (!query.data || query.data.length === 0),
  };
}

// Helper to format currency
export function formatCurrency(value: number | undefined): string {
  if (value === undefined) return '-';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

// Helper to format large numbers (market cap, volume)
export function formatLargeNumber(value: number | undefined): string {
  if (value === undefined) return '-';
  if (value >= 1e12) {
    return `$${(value / 1e12).toFixed(2)}T`;
  }
  if (value >= 1e9) {
    return `$${(value / 1e9).toFixed(2)}B`;
  }
  if (value >= 1e6) {
    return `$${(value / 1e6).toFixed(2)}M`;
  }
  return `$${value.toLocaleString()}`;
}

// Helper to format percentage
export function formatPercent(value: number | undefined): string {
  if (value === undefined) return '-';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

// Helper to get color class for change values
export function getChangeColorClass(value: number | undefined): string {
  if (value === undefined) return 'text-muted-foreground';
  if (value > 0) return 'text-green-600 dark:text-green-500';
  if (value < 0) return 'text-red-600 dark:text-red-500';
  return 'text-muted-foreground';
}
