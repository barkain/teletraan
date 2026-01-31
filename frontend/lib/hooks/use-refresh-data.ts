'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { refreshData } from '@/lib/api';
import type { RefreshDataResponse } from '@/types';

/**
 * Custom hook for refreshing market data
 * Uses mutation to trigger a data refresh and automatically invalidates
 * relevant queries to update the UI with fresh data.
 *
 * @example
 * ```tsx
 * const { mutate: refresh, isPending } = useRefreshData();
 *
 * // Refresh all tracked symbols
 * refresh();
 *
 * // Refresh specific symbols
 * refresh(['AAPL', 'GOOGL', 'MSFT']);
 * ```
 */
export function useRefreshData() {
  const queryClient = useQueryClient();

  return useMutation<RefreshDataResponse, Error, string[] | undefined>({
    mutationFn: (symbols?: string[]) => refreshData(symbols),
    onSuccess: () => {
      // Invalidate relevant queries to refresh UI
      queryClient.invalidateQueries({ queryKey: ['stocks'] });
      queryClient.invalidateQueries({ queryKey: ['market'] });
      queryClient.invalidateQueries({ queryKey: ['market-overview'] });
      queryClient.invalidateQueries({ queryKey: ['tracked-stocks'] });
    },
  });
}
