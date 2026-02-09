import { Clock, Loader2, CheckCircle, XCircle, Ban } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ResearchStatus } from '@/lib/types/research';

const statusConfig: Record<
  ResearchStatus,
  { icon: typeof Clock; color: string; label: string }
> = {
  PENDING: {
    icon: Clock,
    color: 'bg-amber-500/15 text-amber-700 border-amber-200 dark:text-amber-400 dark:border-amber-800',
    label: 'Pending',
  },
  RUNNING: {
    icon: Loader2,
    color: 'bg-blue-500/15 text-blue-700 border-blue-200 dark:text-blue-400 dark:border-blue-800',
    label: 'Running',
  },
  COMPLETED: {
    icon: CheckCircle,
    color: 'bg-green-500/15 text-green-700 border-green-200 dark:text-green-400 dark:border-green-800',
    label: 'Completed',
  },
  FAILED: {
    icon: XCircle,
    color: 'bg-red-500/15 text-red-700 border-red-200 dark:text-red-400 dark:border-red-800',
    label: 'Failed',
  },
  CANCELLED: {
    icon: Ban,
    color: 'bg-gray-500/15 text-gray-700 border-gray-200 dark:text-gray-400 dark:border-gray-800',
    label: 'Cancelled',
  },
};

interface ResearchStatusBadgeProps {
  status: ResearchStatus;
  className?: string;
}

export function ResearchStatusBadge({ status, className }: ResearchStatusBadgeProps) {
  const config = statusConfig[status];
  const Icon = config.icon;
  const isSpinning = status === 'RUNNING';

  return (
    <Badge
      variant="outline"
      className={cn(config.color, className)}
    >
      <Icon className={cn('h-3 w-3', isSpinning && 'animate-spin')} />
      {config.label}
    </Badge>
  );
}
