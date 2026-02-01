'use client';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api';
import { toast } from 'sonner';
import { useEffect } from 'react';
import type { Stock, Insight } from '@/types';

// Market index data type
export interface MarketIndex {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  last_updated: string;
}

// Sector performance type
export interface SectorPerformance {
  name: string;
  symbol: string;
  change_percent: number;
  volume: number;
}

// Dashboard stats type
export interface DashboardStats {
  total_stocks: number;
  active_insights: number;
  last_analysis: string | null;
  data_freshness: string;
}

// Market overview response
interface MarketOverviewResponse {
  indices: MarketIndex[];
  sectors: SectorPerformance[];
  stats: DashboardStats;
}

const REFRESH_INTERVAL = 60 * 1000; // 60 seconds

/**
 * Custom hook for fetching market overview data
 * Auto-refreshes every 60 seconds
 * Combines data from stocks, insights, and sectors endpoints
 */
export function useMarketOverview() {
  const queryClient = useQueryClient();

  const query = useQuery<MarketOverviewResponse>({
    queryKey: ['market-overview'],
    queryFn: async () => {
      // Fetch data from multiple v1 API endpoints in parallel
      const [stocksResult, insightsResult, sectorsResult] = await Promise.allSettled([
        api.stocks.list({ limit: 100 }),
        api.insights.list({ per_page: 100 }),
        api.analysis.sectors(),
      ]);

      // Extract stocks data
      const stocks = stocksResult.status === 'fulfilled' ? stocksResult.value : null;
      const insights = insightsResult.status === 'fulfilled' ? insightsResult.value : null;
      const sectors = sectorsResult.status === 'fulfilled' ? sectorsResult.value : null;

      // Build indices from major ETF stocks (SPY, QQQ, DIA)
      const indexSymbols = ['SPY', 'QQQ', 'DIA'];
      const indices: MarketIndex[] = [];

      if (stocks?.items) {
        for (const symbol of indexSymbols) {
          const stock = stocks.items.find(s => s.symbol === symbol);
          if (stock) {
            indices.push({
              symbol: stock.symbol,
              name: symbol === 'SPY' ? 'S&P 500' : symbol === 'QQQ' ? 'NASDAQ 100' : 'DOW Jones',
              price: stock.current_price ?? 0,
              change: (stock.current_price ?? 0) * (stock.change_percent ?? 0) / 100,
              change_percent: stock.change_percent ?? 0,
              last_updated: stock.updated_at ?? new Date().toISOString(),
            });
          }
        }
      }

      // Build sector performance from sectors API
      const sectorPerformance: SectorPerformance[] = sectors?.sectors?.map(s => ({
        name: s.name,
        symbol: s.symbol,
        change_percent: s.performance,
        volume: s.volume,
      })) ?? [];

      // Build stats
      const stats: DashboardStats = {
        total_stocks: stocks?.total ?? 0,
        active_insights: insights?.total ?? 0,
        last_analysis: sectors?.last_updated ?? null,
        data_freshness: stocks ? 'Real-time' : 'Unavailable',
      };

      return {
        indices,
        sectors: sectorPerformance,
        stats,
      };
    },
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });

  // Show error toast on fetch error
  useEffect(() => {
    if (query.error) {
      toast.error('Failed to fetch market data', {
        description: query.error instanceof ApiError
          ? `Server error: ${query.error.status}`
          : 'Please check your connection and try again.',
      });
    }
  }, [query.error]);

  const refetch = () => {
    queryClient.invalidateQueries({ queryKey: ['market-overview'] });
  };

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (
      !query.data ||
      (query.data.indices.length === 0 && query.data.sectors.length === 0)
    ),
    refetch,
  };
}

/**
 * Custom hook for fetching recent insights
 * Uses the v1 insights API with pagination
 */
export function useRecentInsights(limit: number = 5) {
  const query = useQuery<Insight[]>({
    queryKey: ['recent-insights', limit],
    queryFn: async () => {
      const response = await api.insights.list({ per_page: limit, page: 1 });
      return response.items;
    },
    refetchInterval: REFRESH_INTERVAL * 2, // Refresh every 2 minutes
    staleTime: REFRESH_INTERVAL,
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });

  useEffect(() => {
    if (query.error) {
      toast.error('Failed to fetch insights', {
        description: query.error instanceof ApiError
          ? `Server error: ${(query.error as ApiError).status}`
          : 'Unable to load recent insights.',
      });
    }
  }, [query.error]);

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (!query.data || query.data.length === 0),
  };
}

/**
 * Custom hook for fetching tracked stocks
 * Uses the v1 stocks API
 */
export function useTrackedStocks() {
  const query = useQuery<Stock[]>({
    queryKey: ['tracked-stocks'],
    queryFn: async () => {
      const response = await api.stocks.list();
      return response.items;
    },
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (!query.data || query.data.length === 0),
  };
}
