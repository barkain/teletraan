'use client';

import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { toast } from 'sonner';
import { useEffect } from 'react';
import type { Stock, PriceHistory, Insight, PaginatedResponse } from '@/types';

// Mock stock data for fallback
const MOCK_STOCK: Stock = {
  symbol: 'AAPL',
  name: 'Apple Inc.',
  sector: 'Technology',
  current_price: 185.92,
  change_percent: 1.23,
  market_cap: 2890000000000,
  volume: 52000000,
};

// Mock price history generator
function generateMockPriceHistory(days: number): PriceHistory[] {
  const history: PriceHistory[] = [];
  let basePrice = 180;
  const today = new Date();

  for (let i = days; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);

    const volatility = (Math.random() - 0.5) * 6;
    basePrice = Math.max(150, Math.min(200, basePrice + volatility));

    const open = basePrice + (Math.random() - 0.5) * 2;
    const close = basePrice + (Math.random() - 0.5) * 2;
    const high = Math.max(open, close) + Math.random() * 2;
    const low = Math.min(open, close) - Math.random() * 2;

    history.push({
      date: date.toISOString().split('T')[0],
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close: Number(close.toFixed(2)),
      volume: Math.floor(Math.random() * 50000000) + 30000000,
    });
  }

  return history;
}

/**
 * Custom hook for fetching stock details
 * Uses the v1 stocks API
 */
export function useStock(symbol: string | undefined) {
  const query = useQuery<Stock>({
    queryKey: ['stock', symbol],
    queryFn: async () => {
      try {
        return await api.stocks.get(symbol!);
      } catch (error) {
        console.warn(`Stock API unavailable for ${symbol}, using mock data:`, error);
        return { ...MOCK_STOCK, symbol: symbol! };
      }
    },
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

  return query;
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
    queryFn: async () => {
      try {
        return await api.stocks.history(symbol!, { days });
      } catch (error) {
        console.warn(`Price history API unavailable for ${symbol}, using mock data:`, error);
        return generateMockPriceHistory(days);
      }
    },
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

  return query;
}

/**
 * Custom hook for fetching all stocks
 * Uses the v1 stocks API with pagination
 */
export function useStocks(params?: { sector?: string; limit?: number }) {
  const query = useQuery<Stock[]>({
    queryKey: ['stocks', params?.sector, params?.limit],
    queryFn: async () => {
      try {
        const response = await api.stocks.list({
          sector: params?.sector,
          limit: params?.limit ?? 100,
        });
        return response.items;
      } catch (error) {
        console.warn('Stocks API unavailable, using mock data:', error);
        return [MOCK_STOCK];
      }
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

  return query;
}

/**
 * Custom hook for fetching insights related to a stock
 * Uses the v1 insights API with symbol filter
 */
export function useStockInsights(symbol: string | undefined) {
  const query = useQuery<Insight[]>({
    queryKey: ['stock-insights', symbol],
    queryFn: async () => {
      try {
        const response = await api.insights.list({ symbol, per_page: 10 });
        return response.items;
      } catch (error) {
        console.warn(`Insights API unavailable for ${symbol}:`, error);
        return [];
      }
    },
    enabled: !!symbol,
    staleTime: 60 * 1000, // 1 minute
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 5000),
  });

  return query;
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
