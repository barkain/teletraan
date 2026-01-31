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

// Mock data fallback
const MOCK_MARKET_DATA: MarketOverviewResponse = {
  indices: [
    { symbol: 'SPY', name: 'S&P 500', price: 4783.45, change: 58.23, change_percent: 1.23, last_updated: new Date().toISOString() },
    { symbol: 'QQQ', name: 'NASDAQ 100', price: 14972.76, change: 129.52, change_percent: 0.87, last_updated: new Date().toISOString() },
    { symbol: 'DIA', name: 'DOW Jones', price: 37545.33, change: -56.18, change_percent: -0.15, last_updated: new Date().toISOString() },
  ],
  sectors: [
    { name: 'Technology', symbol: 'XLK', change_percent: 1.85, volume: 125000000 },
    { name: 'Healthcare', symbol: 'XLV', change_percent: 0.42, volume: 89000000 },
    { name: 'Financials', symbol: 'XLF', change_percent: -0.23, volume: 112000000 },
    { name: 'Energy', symbol: 'XLE', change_percent: -1.15, volume: 78000000 },
    { name: 'Consumer', symbol: 'XLY', change_percent: 0.67, volume: 95000000 },
    { name: 'Industrial', symbol: 'XLI', change_percent: 0.31, volume: 67000000 },
  ],
  stats: {
    total_stocks: 45,
    active_insights: 12,
    last_analysis: new Date().toISOString(),
    data_freshness: 'Real-time',
  },
};

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
      try {
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

        // Use mock indices if none found
        if (indices.length === 0) {
          indices.push(...MOCK_MARKET_DATA.indices);
        }

        // Build sector performance from sectors API
        const sectorPerformance: SectorPerformance[] = sectors?.sectors?.map(s => ({
          name: s.name,
          symbol: s.symbol,
          change_percent: s.performance,
          volume: s.volume,
        })) ?? MOCK_MARKET_DATA.sectors;

        // Build stats
        const stats: DashboardStats = {
          total_stocks: stocks?.total ?? MOCK_MARKET_DATA.stats.total_stocks,
          active_insights: insights?.total ?? MOCK_MARKET_DATA.stats.active_insights,
          last_analysis: sectors?.last_updated ?? MOCK_MARKET_DATA.stats.last_analysis,
          data_freshness: stocks ? 'Real-time' : 'Cached',
        };

        return {
          indices,
          sectors: sectorPerformance,
          stats,
        };
      } catch (error) {
        // Return mock data if API is unavailable
        console.warn('Market overview API unavailable, using mock data:', error);
        return MOCK_MARKET_DATA;
      }
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
    refetch,
  };
}

// Mock insights fallback
const MOCK_INSIGHTS: Insight[] = [
  {
    id: '1',
    symbol: 'AAPL',
    type: 'technical' as const,
    severity: 'info' as const,
    title: 'Strong support at $180',
    content: 'Technical analysis indicates strong support at $180, potential breakout above $190',
    confidence: 0.85,
    created_at: new Date(Date.now() - 3600000).toISOString(),
  },
  {
    id: '2',
    symbol: 'GOOGL',
    type: 'technical' as const,
    severity: 'info' as const,
    title: 'Q4 Earnings Preview',
    content: 'Q4 earnings expected to show cloud growth momentum',
    confidence: 0.72,
    created_at: new Date(Date.now() - 7200000).toISOString(),
  },
  {
    id: '3',
    symbol: 'MSFT',
    type: 'pattern' as const,
    severity: 'warning' as const,
    title: 'AI Investment Drives Growth',
    content: 'OpenAI partnership continues to drive enterprise AI adoption',
    confidence: 0.91,
    created_at: new Date(Date.now() - 10800000).toISOString(),
  },
  {
    id: '4',
    symbol: 'NVDA',
    type: 'anomaly' as const,
    severity: 'alert' as const,
    title: 'Data Center Demand Surge',
    content: 'AI chip demand exceeds supply, boosting revenue outlook',
    confidence: 0.88,
    created_at: new Date(Date.now() - 14400000).toISOString(),
  },
  {
    id: '5',
    symbol: 'AMZN',
    type: 'technical' as const,
    severity: 'info' as const,
    title: 'Breaking Resistance',
    content: 'AWS growth accelerating, e-commerce showing recovery',
    confidence: 0.79,
    created_at: new Date(Date.now() - 18000000).toISOString(),
  },
];

/**
 * Custom hook for fetching recent insights
 * Uses the v1 insights API with pagination
 */
export function useRecentInsights(limit: number = 5) {
  const query = useQuery<Insight[]>({
    queryKey: ['recent-insights', limit],
    queryFn: async () => {
      try {
        const response = await api.insights.list({ per_page: limit, page: 1 });
        return response.items;
      } catch (error) {
        // Return mock data if API is unavailable
        console.warn('Insights API unavailable, using mock data:', error);
        return MOCK_INSIGHTS.slice(0, limit);
      }
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

  return query;
}

// Mock tracked stocks fallback
const MOCK_TRACKED_STOCKS: Stock[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', sector: 'Technology', current_price: 185.92, change_percent: 1.23 },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', sector: 'Technology', current_price: 141.80, change_percent: 0.87 },
  { symbol: 'MSFT', name: 'Microsoft Corporation', sector: 'Technology', current_price: 378.91, change_percent: 1.45 },
  { symbol: 'AMZN', name: 'Amazon.com Inc.', sector: 'Consumer', current_price: 155.34, change_percent: -0.32 },
];

/**
 * Custom hook for fetching tracked stocks
 * Uses the v1 stocks API
 */
export function useTrackedStocks() {
  return useQuery<Stock[]>({
    queryKey: ['tracked-stocks'],
    queryFn: async () => {
      try {
        const response = await api.stocks.list();
        return response.items;
      } catch (error) {
        // Return mock data if API is unavailable
        console.warn('Stocks API unavailable, using mock data:', error);
        return MOCK_TRACKED_STOCKS;
      }
    },
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });
}
