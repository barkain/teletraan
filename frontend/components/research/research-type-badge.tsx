import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ResearchType } from '@/lib/types/research';

const typeConfig: Record<ResearchType, { color: string; label: string }> = {
  DEEP_DIVE: {
    color: 'bg-purple-500/15 text-purple-700 border-purple-200 dark:text-purple-400 dark:border-purple-800',
    label: 'Deep Dive',
  },
  SCENARIO_ANALYSIS: {
    color: 'bg-orange-500/15 text-orange-700 border-orange-200 dark:text-orange-400 dark:border-orange-800',
    label: 'Scenario Analysis',
  },
  WHAT_IF: {
    color: 'bg-orange-500/15 text-orange-700 border-orange-200 dark:text-orange-400 dark:border-orange-800',
    label: 'What If',
  },
  CORRELATION_CHECK: {
    color: 'bg-blue-500/15 text-blue-700 border-blue-200 dark:text-blue-400 dark:border-blue-800',
    label: 'Correlation',
  },
  SECTOR_DEEP_DIVE: {
    color: 'bg-green-500/15 text-green-700 border-green-200 dark:text-green-400 dark:border-green-800',
    label: 'Sector Deep Dive',
  },
  TECHNICAL_FOCUS: {
    color: 'bg-cyan-500/15 text-cyan-700 border-cyan-200 dark:text-cyan-400 dark:border-cyan-800',
    label: 'Technical Focus',
  },
  MACRO_IMPACT: {
    color: 'bg-red-500/15 text-red-700 border-red-200 dark:text-red-400 dark:border-red-800',
    label: 'Macro Impact',
  },
};

interface ResearchTypeBadgeProps {
  type: ResearchType;
  className?: string;
}

export function ResearchTypeBadge({ type, className }: ResearchTypeBadgeProps) {
  const config = typeConfig[type];

  return (
    <Badge
      variant="outline"
      className={cn(config.color, className)}
    >
      {config.label}
    </Badge>
  );
}
