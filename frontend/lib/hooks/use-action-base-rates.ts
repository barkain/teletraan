'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchApi } from '@/lib/api';
import type { ActionBaseRate, ActionBaseRates } from '@/types';

export const actionBaseRateKeys = {
  all: ['action-base-rates'] as const,
};

/**
 * How often each action type has actually worked, from the graded outcome record.
 *
 * This is the number the UI shows in place of an insight's stated confidence.
 * One fetch serves every insight view: the rate is a property of the action
 * type, not of the individual idea, so there is nothing per-insight to fetch.
 */
export function useActionBaseRates() {
  return useQuery<ActionBaseRates>({
    queryKey: actionBaseRateKeys.all,
    queryFn: () => fetchApi<ActionBaseRates>('/api/v1/knowledge/action-base-rates'),
    // The graded record only moves when an outcome window closes, which happens
    // at most once a day.
    staleTime: 30 * 60 * 1000,
  });
}

/**
 * Pick the record for one action out of a fetched set.
 *
 * Returns null while the fetch is in flight or if it failed, which callers must
 * render as "unknown" rather than as a rate of zero. An action the record has
 * never seen comes back as a real entry with `graded: 0`, so a brand-new action
 * label reads as unmeasured rather than as missing.
 */
export function selectActionBaseRate(
  rates: ActionBaseRates | undefined,
  action: string | undefined | null,
): ActionBaseRate | null {
  if (!rates || !action) return null;
  return (
    rates.by_action[action.toUpperCase()] ?? {
      action: action.toUpperCase(),
      graded: 0,
      validated: 0,
      rate: null,
      percent: null,
      available: false,
      headline: `Too few graded ${action.toUpperCase()} calls (n=0)`,
      caveat: rates.caveat,
    }
  );
}
