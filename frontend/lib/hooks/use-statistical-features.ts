'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchApi, postApi, ApiError } from '@/lib/api';
import { toast } from 'sonner';
import { useEffect } from 'react';
import type {
  StatisticalFeature,
  StatisticalFeaturesResponse,
  ActiveSignal,
  ActiveSignalsResponse,
  ActiveSignalsParams,
  ComputeFeaturesResponse,
  ComputeFeaturesRequest,
  SignalStrength,
} from '@/lib/types/statistical-features';

// Query keys for cache management
export const statisticalFeaturesKeys = {
  all: ['statistical-features'] as const,
  features: (symbol: string) => [...statisticalFeaturesKeys.all, 'features', symbol] as const,
  signals: (params?: ActiveSignalsParams) => [...statisticalFeaturesKeys.all, 'signals', params] as const,
};

// Refresh intervals
const FEATURES_REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes
const SIGNALS_REFRESH_INTERVAL = 60 * 1000; // 1 minute

/**
 * Hook for fetching statistical features for a specific symbol
 * @param symbol - The stock symbol to fetch features for
 * @returns Query result with features, loading state, error, and refetch function
 */
export function useStatisticalFeatures(symbol: string) {
  const queryClient = useQueryClient();

  const query = useQuery<StatisticalFeaturesResponse>({
    queryKey: statisticalFeaturesKeys.features(symbol),
    queryFn: () => fetchApi<StatisticalFeaturesResponse>(
      `/api/v1/features/${encodeURIComponent(symbol)}`
    ),
    enabled: !!symbol,
    refetchInterval: FEATURES_REFRESH_INTERVAL,
    staleTime: FEATURES_REFRESH_INTERVAL / 2,
    retry: (failureCount, error) => {
      // Don't retry 404s - they mean no features computed yet
      if (error instanceof ApiError && error.status === 404) {
        return false;
      }
      return failureCount < 2;
    },
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });

  // Show error toast on fetch error (but not for 404s - that just means no features computed yet)
  useEffect(() => {
    if (query.error) {
      const is404 = query.error instanceof ApiError && query.error.status === 404;

      if (!is404) {
        toast.error(`Failed to fetch features for ${symbol}`, {
          description: query.error instanceof ApiError
            ? `Server error: ${query.error.status}`
            : 'Please check your connection and try again.',
        });
      }
    }
  }, [query.error, symbol]);

  const refetch = () => {
    queryClient.invalidateQueries({ queryKey: statisticalFeaturesKeys.features(symbol) });
  };

  // Treat 404 as empty data, not an error
  const is404 = query.error instanceof ApiError && query.error.status === 404;
  const hasError = query.isError && !is404;

  return {
    features: query.data?.features ?? [],
    calculationDate: query.data?.calculation_date,
    isLoading: query.isLoading,
    isError: hasError,
    error: is404 ? null : query.error,
    isEmpty: !query.isLoading && (!query.data?.features || query.data.features.length === 0),
    refetch,
  };
}

/**
 * Hook for fetching all active signals across the watchlist
 * @param options - Optional filtering parameters
 * @returns Query result with signals, count, loading state, error, and refetch function
 */
export function useActiveSignals(options?: {
  signalType?: string;
  minStrength?: SignalStrength;
}) {
  const queryClient = useQueryClient();

  // Build params object
  const params: ActiveSignalsParams = {};
  if (options?.signalType) params.signal_type = options.signalType;
  if (options?.minStrength) params.min_strength = options.minStrength;

  const query = useQuery<ActiveSignalsResponse>({
    queryKey: statisticalFeaturesKeys.signals(params),
    queryFn: () => fetchApi<ActiveSignalsResponse>('/api/v1/features/signals', {
      params: params as Record<string, string | number | boolean | undefined>,
    }),
    refetchInterval: SIGNALS_REFRESH_INTERVAL,
    staleTime: SIGNALS_REFRESH_INTERVAL / 2,
    retry: (failureCount, error) => {
      // Don't retry 404s - they mean no signals available yet
      if (error instanceof ApiError && error.status === 404) {
        return false;
      }
      return failureCount < 2;
    },
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });

  // Show error toast on fetch error (but not for 404s - that just means no signals yet)
  useEffect(() => {
    if (query.error) {
      const is404 = query.error instanceof ApiError && query.error.status === 404;

      if (!is404) {
        toast.error('Failed to fetch active signals', {
          description: query.error instanceof ApiError
            ? `Server error: ${(query.error as ApiError).status}`
            : 'Unable to load active signals.',
        });
      }
    }
  }, [query.error]);

  const refetch = () => {
    queryClient.invalidateQueries({ queryKey: statisticalFeaturesKeys.signals(params) });
  };

  // Treat 404 as empty data, not an error
  const is404 = query.error instanceof ApiError && query.error.status === 404;
  const hasError = query.isError && !is404;

  return {
    signals: query.data?.signals ?? [],
    count: query.data?.count ?? 0,
    asOf: query.data?.as_of,
    isLoading: query.isLoading,
    isError: hasError,
    error: is404 ? null : query.error,
    isEmpty: !query.isLoading && (!query.data?.signals || query.data.signals.length === 0),
    refetch,
  };
}

/**
 * Hook for triggering feature computation
 * @returns Mutation with compute function, computing state, and error
 */
export function useComputeFeatures() {
  const queryClient = useQueryClient();

  const mutation = useMutation<ComputeFeaturesResponse, Error, string[] | undefined>({
    mutationFn: async (symbols?: string[]) => {
      const body: ComputeFeaturesRequest = symbols ? { symbols } : {};
      return postApi<ComputeFeaturesResponse>('/api/v1/features/compute', body);
    },
    onSuccess: (data) => {
      // Invalidate all features queries to refetch fresh data
      queryClient.invalidateQueries({ queryKey: statisticalFeaturesKeys.all });

      toast.success('Feature computation started', {
        description: data.message || `Processing ${data.symbols_processed?.length ?? 'all'} symbols`,
      });
    },
    onError: (error) => {
      toast.error('Failed to start feature computation', {
        description: error instanceof ApiError
          ? `Server error: ${error.status}`
          : error.message || 'Please try again later.',
      });
    },
  });

  return {
    compute: mutation.mutate,
    computeAsync: mutation.mutateAsync,
    isComputing: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error,
    data: mutation.data,
    reset: mutation.reset,
  };
}

// Re-export types for convenience
export type {
  StatisticalFeature,
  StatisticalFeaturesResponse,
  ActiveSignal,
  ActiveSignalsResponse,
  SignalStrength,
} from '@/lib/types/statistical-features';
