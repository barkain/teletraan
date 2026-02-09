'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Portfolio, PortfolioHolding, HoldingCreate, HoldingUpdate, PortfolioImpact } from '@/types';

// Query keys for portfolio
export const portfolioKeys = {
  all: ['portfolio'] as const,
  detail: () => [...portfolioKeys.all, 'detail'] as const,
  impact: () => [...portfolioKeys.all, 'impact'] as const,
};

/**
 * Custom hook for fetching the portfolio with all holdings
 */
export function usePortfolio() {
  return useQuery<Portfolio>({
    queryKey: portfolioKeys.detail(),
    queryFn: () => api.portfolio.get(),
    staleTime: 60_000, // 1 minute
    gcTime: 600_000, // 10 minutes cache
  });
}

/**
 * Custom hook for fetching portfolio impact analysis
 */
export function usePortfolioImpact(enabled?: boolean) {
  return useQuery<PortfolioImpact>({
    queryKey: portfolioKeys.impact(),
    queryFn: () => api.portfolio.impact(),
    staleTime: 300_000, // 5 minutes
    gcTime: 600_000, // 10 minutes cache
    enabled,
  });
}

/**
 * Custom hook for adding a holding to the portfolio
 */
export function useAddHolding() {
  const queryClient = useQueryClient();

  return useMutation<PortfolioHolding, Error, HoldingCreate>({
    mutationFn: (holding) => api.portfolio.addHolding(holding),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.all });
    },
  });
}

/**
 * Custom hook for updating a holding in the portfolio
 */
export function useUpdateHolding() {
  const queryClient = useQueryClient();

  return useMutation<PortfolioHolding, Error, { holdingId: number; data: HoldingUpdate }>({
    mutationFn: ({ holdingId, data }) => api.portfolio.updateHolding(holdingId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: portfolioKeys.all });
    },
  });
}

// Context type for optimistic delete
type DeleteHoldingContext = { previousPortfolio: Portfolio | undefined };

/**
 * Custom hook for deleting a holding with optimistic update
 */
export function useDeleteHolding() {
  const queryClient = useQueryClient();

  return useMutation<void, Error, number, DeleteHoldingContext>({
    mutationFn: (holdingId) => api.portfolio.deleteHolding(holdingId),
    onMutate: async (holdingId) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: portfolioKeys.detail() });

      // Snapshot previous value
      const previousPortfolio = queryClient.getQueryData<Portfolio>(
        portfolioKeys.detail()
      );

      // Optimistically remove the holding
      if (previousPortfolio) {
        queryClient.setQueryData<Portfolio>(
          portfolioKeys.detail(),
          {
            ...previousPortfolio,
            holdings: previousPortfolio.holdings.filter(
              (holding) => holding.id !== holdingId
            ),
          }
        );
      }

      return { previousPortfolio };
    },
    onError: (_, __, context) => {
      // Rollback on error
      if (context?.previousPortfolio) {
        queryClient.setQueryData(portfolioKeys.detail(), context.previousPortfolio);
      }
    },
    onSettled: () => {
      // Refetch to ensure server state
      queryClient.invalidateQueries({ queryKey: portfolioKeys.all });
    },
  });
}
