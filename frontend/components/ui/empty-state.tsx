import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { WifiOff } from 'lucide-react';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

// ============================================
// Empty State Component
// ============================================

interface EmptyStateAction {
  label: string;
  href?: string;
  onClick?: () => void;
}

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: EmptyStateAction;
  className?: string;
}

export function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <Card className={className ?? 'py-12'}>
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Icon className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">{title}</CardTitle>
        <CardDescription className="max-w-sm">
          {description}
        </CardDescription>
        {action && (
          <div className="mt-6">
            {action.href ? (
              <Button asChild>
                <Link href={action.href}>{action.label}</Link>
              </Button>
            ) : action.onClick ? (
              <Button onClick={action.onClick}>{action.label}</Button>
            ) : null}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================
// Connection Error Component
// ============================================

interface ConnectionErrorProps {
  error?: unknown;
  className?: string;
}

/**
 * Determines if a fetch error is a network/connection error
 * (as opposed to a server-side error like 404 or 500).
 */
export function isNetworkError(error: unknown): boolean {
  if (!error) return false;
  if (error instanceof TypeError && error.message === 'Failed to fetch') return true;
  if (error instanceof Error) {
    const msg = error.message.toLowerCase();
    return (
      msg.includes('network') ||
      msg.includes('failed to fetch') ||
      msg.includes('econnrefused') ||
      msg.includes('econnreset') ||
      msg.includes('load failed') ||
      msg.includes('networkerror')
    );
  }
  return false;
}

export function ConnectionError({ error, className }: ConnectionErrorProps) {
  const isNetwork = isNetworkError(error);

  return (
    <Card className={className ?? 'py-12'}>
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-destructive/10 p-4 mb-4">
          <WifiOff className="h-8 w-8 text-destructive" />
        </div>
        <CardTitle className="text-lg mb-2">
          {isNetwork ? 'Cannot Reach Backend' : 'Something Went Wrong'}
        </CardTitle>
        <CardDescription className="max-w-sm">
          {isNetwork
            ? 'Check that the backend server is running and try again.'
            : error instanceof Error
              ? error.message
              : 'An unexpected error occurred. Please try again later.'}
        </CardDescription>
      </CardContent>
    </Card>
  );
}
