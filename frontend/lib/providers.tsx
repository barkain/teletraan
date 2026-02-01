'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Toaster } from '@/components/ui/sonner';

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute - data is fresh for 1 min
            gcTime: 10 * 60 * 1000, // 10 minutes - keep in cache for stale-while-revalidate
            refetchOnWindowFocus: false,
            refetchOnMount: true, // Refetch stale data on mount
            retry: 1, // Only retry once to avoid long waits
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
