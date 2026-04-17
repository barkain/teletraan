'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { useAuth } from '@/contexts/auth-context';
import { TrendingUp } from 'lucide-react';

/**
 * Renders children only when the user is authenticated.
 * Redirects to /login otherwise. The /login path itself is always rendered.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isLoginPage = pathname === '/login';

  useEffect(() => {
    if (!isLoading && !user && !isLoginPage) {
      router.replace('/login');
    }
    if (!isLoading && user && isLoginPage) {
      router.replace('/');
    }
  }, [isLoading, user, isLoginPage, router]);

  // While checking session — show minimal spinner
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-indigo-50 to-slate-100 dark:from-slate-950 dark:via-purple-950 dark:to-slate-950">
        <div className="flex flex-col items-center gap-4 text-muted-foreground">
          <div className="rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 p-4 animate-pulse">
            <TrendingUp className="h-7 w-7 text-white" />
          </div>
          <p className="text-sm">Loading…</p>
        </div>
      </div>
    );
  }

  // Login page: always render (redirect away handled in useEffect above)
  if (isLoginPage) return <>{children}</>;

  // Not authenticated: render nothing (redirect in progress)
  if (!user) return null;

  return <>{children}</>;
}
