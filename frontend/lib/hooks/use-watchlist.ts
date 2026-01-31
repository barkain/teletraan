'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, putApi, fetchApi } from '@/lib/api';
import type { WatchlistSettings, SettingsResponse } from '@/types';

// Query keys for watchlist
export const watchlistKeys = {
  all: ['watchlist'] as const,
};

// Custom hook for fetching the watchlist
export function useWatchlist() {
  return useQuery<WatchlistSettings>({
    queryKey: watchlistKeys.all,
    queryFn: async () => {
      // Use the main settings endpoint and extract watchlist
      const response = await api.settings.get();
      return {
        symbols: response.settings.watchlist_symbols || [],
        last_refresh: null, // The API doesn't track this separately
      };
    },
    staleTime: 60 * 1000, // 1 minute
  });
}

// Custom hook for updating the watchlist
export function useUpdateWatchlist() {
  const queryClient = useQueryClient();

  return useMutation<WatchlistSettings, Error, string[]>({
    mutationFn: async (symbols: string[]) => {
      // Update the watchlist_symbols setting
      await api.settings.update('watchlist_symbols', symbols);
      return {
        symbols,
        last_refresh: null,
      };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: watchlistKeys.all });
    },
  });
}
