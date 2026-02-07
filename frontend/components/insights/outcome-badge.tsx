'use client';

import * as React from 'react';
import { useInsightOutcome } from '@/lib/hooks/use-track-record';
import type { OutcomeCategory, TrackingStatus } from '@/lib/types/track-record';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import {
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  Minus,
  TrendingUp,
  TrendingDown,
  Loader2,
} from 'lucide-react';

// ============================================
// Types
// ============================================

interface OutcomeBadgeProps {
  insightId: number | string;
  size?: 'sm' | 'md' | 'lg';
  showDetails?: boolean;
  className?: string;
}

// ============================================
// Constants
// ============================================

const OUTCOME_CONFIG: Record<OutcomeCategory, {
  label: string;
  color: string;
  bgColor: string;
  icon: React.ElementType;
}> = {
  STRONG_SUCCESS: {
    label: 'Strong Success',
    color: 'text-green-700 dark:text-green-400',
    bgColor: 'bg-green-100 dark:bg-green-900/30',
    icon: CheckCircle2,
  },
  SUCCESS: {
    label: 'Success',
    color: 'text-green-600 dark:text-green-400',
    bgColor: 'bg-green-50 dark:bg-green-900/20',
    icon: CheckCircle2,
  },
  PARTIAL_SUCCESS: {
    label: 'Partial Success',
    color: 'text-green-500 dark:text-green-500',
    bgColor: 'bg-green-50/50 dark:bg-green-900/10',
    icon: TrendingUp,
  },
  NEUTRAL: {
    label: 'Neutral',
    color: 'text-gray-600 dark:text-gray-400',
    bgColor: 'bg-gray-100 dark:bg-gray-800/30',
    icon: Minus,
  },
  PARTIAL_FAILURE: {
    label: 'Partial Failure',
    color: 'text-red-500 dark:text-red-500',
    bgColor: 'bg-red-50/50 dark:bg-red-900/10',
    icon: TrendingDown,
  },
  FAILURE: {
    label: 'Failure',
    color: 'text-red-600 dark:text-red-400',
    bgColor: 'bg-red-50 dark:bg-red-900/20',
    icon: XCircle,
  },
  STRONG_FAILURE: {
    label: 'Strong Failure',
    color: 'text-red-700 dark:text-red-400',
    bgColor: 'bg-red-100 dark:bg-red-900/30',
    icon: XCircle,
  },
};

const STATUS_CONFIG: Record<TrackingStatus, {
  label: string;
  color: string;
  bgColor: string;
  icon: React.ElementType;
}> = {
  PENDING: {
    label: 'Pending',
    color: 'text-gray-500 dark:text-gray-400',
    bgColor: 'bg-gray-100 dark:bg-gray-800/30',
    icon: Clock,
  },
  TRACKING: {
    label: 'Tracking',
    color: 'text-blue-600 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-900/20',
    icon: Clock,
  },
  COMPLETED: {
    label: 'Completed',
    color: 'text-gray-600 dark:text-gray-400',
    bgColor: 'bg-gray-100 dark:bg-gray-800/30',
    icon: CheckCircle2,
  },
  INVALIDATED: {
    label: 'Invalidated',
    color: 'text-yellow-600 dark:text-yellow-400',
    bgColor: 'bg-yellow-50 dark:bg-yellow-900/20',
    icon: AlertTriangle,
  },
};

const SIZE_CONFIG = {
  sm: {
    badge: 'text-xs px-2 py-0.5',
    icon: 'h-3 w-3',
    gap: 'gap-1',
  },
  md: {
    badge: 'text-sm px-2.5 py-1',
    icon: 'h-4 w-4',
    gap: 'gap-1.5',
  },
  lg: {
    badge: 'text-base px-3 py-1.5',
    icon: 'h-5 w-5',
    gap: 'gap-2',
  },
};

// ============================================
// Helper Functions
// ============================================

function formatPercent(value: number | undefined | null): string {
  if (value === undefined || value === null) return 'N/A';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

function formatDaysRemaining(days: number | undefined): string {
  if (days === undefined) return '';
  if (days <= 0) return 'Ended';
  if (days === 1) return '1 day left';
  return `${days} days left`;
}

// ============================================
// Component
// ============================================

/**
 * OutcomeBadge displays the tracking outcome for a specific insight.
 *
 * Features:
 * - Shows tracking status (pending, tracking, completed, invalidated)
 * - Shows outcome category if completed (success, failure, etc.)
 * - Shows actual return percentage
 * - Supports small, medium, and large sizes
 * - Optional detailed tooltip with more information
 * - Handles loading and error states gracefully
 */
export function OutcomeBadge({
  insightId,
  size = 'sm',
  showDetails = true,
  className,
}: OutcomeBadgeProps) {
  // Convert insightId to string for the API
  const insightIdStr = String(insightId);

  // Fetch outcome data
  const { data: outcome, isLoading, error } = useInsightOutcome(insightIdStr);

  const sizeConfig = SIZE_CONFIG[size];

  // Loading state - render nothing or a subtle loading indicator
  if (isLoading) {
    return (
      <div className={cn('inline-flex items-center', sizeConfig.gap, className)}>
        <Loader2 className={cn(sizeConfig.icon, 'animate-spin text-muted-foreground')} />
      </div>
    );
  }

  // Error state or no outcome - render nothing
  if (error || !outcome) {
    return null;
  }

  // Determine what to show based on status and outcome
  const isCompleted = outcome.tracking_status === 'COMPLETED';
  const hasOutcome = isCompleted && outcome.outcome_category;

  // Get configuration based on outcome or status
  const config = hasOutcome && outcome.outcome_category
    ? OUTCOME_CONFIG[outcome.outcome_category]
    : STATUS_CONFIG[outcome.tracking_status];

  // Guard against unknown tracking_status or outcome_category values
  if (!config) {
    return null;
  }

  const Icon = config.icon;

  // Build the badge content
  const BadgeContent = (
    <Badge
      variant="outline"
      className={cn(
        'inline-flex items-center font-medium border-0',
        sizeConfig.badge,
        sizeConfig.gap,
        config.color,
        config.bgColor,
        className
      )}
    >
      <Icon className={sizeConfig.icon} />
      <span>{hasOutcome ? config.label : config.label}</span>
      {hasOutcome && outcome.actual_return_pct !== undefined && (
        <span className={cn(
          'font-semibold',
          outcome.actual_return_pct >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
        )}>
          {formatPercent(outcome.actual_return_pct)}
        </span>
      )}
      {!isCompleted && outcome.days_remaining !== undefined && outcome.days_remaining > 0 && (
        <span className="text-muted-foreground text-xs">
          ({formatDaysRemaining(outcome.days_remaining)})
        </span>
      )}
    </Badge>
  );

  // If showDetails is false, just return the badge
  if (!showDetails) {
    return BadgeContent;
  }

  // Render with tooltip for additional details
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {BadgeContent}
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        <div className="space-y-2">
          <div className="font-medium">{config.label}</div>

          {/* Price Information */}
          <div className="text-xs space-y-1 text-muted-foreground">
            <div className="flex justify-between gap-4">
              <span>Entry Price:</span>
              <span className="font-medium text-foreground">
                ${outcome.initial_price.toFixed(2)}
              </span>
            </div>

            {outcome.current_price && !isCompleted && (
              <div className="flex justify-between gap-4">
                <span>Current Price:</span>
                <span className="font-medium text-foreground">
                  ${outcome.current_price.toFixed(2)}
                </span>
              </div>
            )}

            {outcome.final_price && isCompleted && (
              <div className="flex justify-between gap-4">
                <span>Exit Price:</span>
                <span className="font-medium text-foreground">
                  ${outcome.final_price.toFixed(2)}
                </span>
              </div>
            )}

            {outcome.actual_return_pct !== undefined && (
              <div className="flex justify-between gap-4">
                <span>Return:</span>
                <span className={cn(
                  'font-medium',
                  outcome.actual_return_pct >= 0 ? 'text-green-600' : 'text-red-600'
                )}>
                  {formatPercent(outcome.actual_return_pct)}
                </span>
              </div>
            )}

            {outcome.predicted_direction && (
              <div className="flex justify-between gap-4">
                <span>Predicted:</span>
                <span className="font-medium text-foreground capitalize">
                  {outcome.predicted_direction}
                </span>
              </div>
            )}

            {!isCompleted && outcome.days_remaining !== undefined && (
              <div className="flex justify-between gap-4">
                <span>Time Remaining:</span>
                <span className="font-medium text-foreground">
                  {formatDaysRemaining(outcome.days_remaining)}
                </span>
              </div>
            )}
          </div>

          {/* Validation Notes */}
          {outcome.validation_notes && (
            <div className="text-xs border-t pt-2 mt-2">
              <div className="font-medium mb-1">Notes:</div>
              <div className="text-muted-foreground">{outcome.validation_notes}</div>
            </div>
          )}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
