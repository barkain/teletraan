'use client';

import Link from 'next/link';
import {
  TrendingUp,
  RefreshCcw,
  Zap,
  Calendar,
  BarChart3,
  Target,
  CheckCircle,
  Clock,
  Hash,
  ExternalLink,
} from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import type { KnowledgePattern, PatternType } from '@/lib/types/knowledge';

// Extended pattern type that may include source_insights from the API
interface ExtendedKnowledgePattern extends KnowledgePattern {
  source_insights?: string[] | null;
  market_conditions?: Record<string, unknown> | null;
}

interface PatternDetailDrawerProps {
  pattern: ExtendedKnowledgePattern | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// Pattern type configuration with colors and icons (consistent with pattern-library-panel)
const patternTypeConfig: Record<
  PatternType,
  { color: string; icon: typeof TrendingUp; label: string }
> = {
  TECHNICAL_SETUP: {
    color: 'bg-blue-500',
    icon: TrendingUp,
    label: 'Technical Setup',
  },
  MACRO_CORRELATION: {
    color: 'bg-purple-500',
    icon: RefreshCcw,
    label: 'Macro Correlation',
  },
  SECTOR_ROTATION: {
    color: 'bg-green-500',
    icon: Zap,
    label: 'Sector Rotation',
  },
  EARNINGS_PATTERN: {
    color: 'bg-amber-500',
    icon: Calendar,
    label: 'Earnings Pattern',
  },
  SEASONALITY: {
    color: 'bg-cyan-500',
    icon: BarChart3,
    label: 'Seasonality',
  },
  CROSS_ASSET: {
    color: 'bg-pink-500',
    icon: Target,
    label: 'Cross Asset',
  },
};

// Lifecycle status badge colors
const lifecycleStatusConfig: Record<string, { color: string; label: string }> = {
  active: { color: 'bg-green-500/15 text-green-600 border-green-500/30', label: 'Active' },
  confirmed: { color: 'bg-emerald-500/15 text-emerald-600 border-emerald-500/30', label: 'Confirmed' },
  emerging: { color: 'bg-blue-500/15 text-blue-600 border-blue-500/30', label: 'Emerging' },
  declining: { color: 'bg-amber-500/15 text-amber-600 border-amber-500/30', label: 'Declining' },
  deprecated: { color: 'bg-red-500/15 text-red-600 border-red-500/30', label: 'Deprecated' },
};

// Sector badge colors (cycling through a palette)
const sectorColors = [
  'bg-violet-500/15 text-violet-700 dark:text-violet-400 border-violet-500/30',
  'bg-teal-500/15 text-teal-700 dark:text-teal-400 border-teal-500/30',
  'bg-orange-500/15 text-orange-700 dark:text-orange-400 border-orange-500/30',
  'bg-sky-500/15 text-sky-700 dark:text-sky-400 border-sky-500/30',
  'bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-500/30',
  'bg-lime-500/15 text-lime-700 dark:text-lime-400 border-lime-500/30',
];

/**
 * Large success rate ring (64px) for the drawer header
 */
function SuccessRateRing({ rate, size = 64 }: { rate: number; size?: number }) {
  const percentage = Math.round(rate * 100);
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - rate * circumference;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg className="rotate-[-90deg]" width={size} height={size}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={5}
          className="text-muted/30"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={5}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          className={cn(
            percentage >= 70
              ? 'text-green-500'
              : percentage >= 50
                ? 'text-amber-500'
                : 'text-red-500'
          )}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-sm font-bold">{percentage}%</span>
      </div>
    </div>
  );
}

/**
 * Format trigger conditions as readable list
 */
function formatTriggerConditions(
  conditions: Record<string, unknown>
): { key: string; value: string }[] {
  return Object.entries(conditions).map(([key, value]) => {
    const formattedKey = key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
    const formattedValue =
      typeof value === 'object' && value !== null
        ? JSON.stringify(value)
        : String(value);
    return { key: formattedKey, value: formattedValue };
  });
}

/**
 * Format a date string to a readable format
 */
function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * Format market conditions JSON into readable key-value pairs
 */
function formatMarketConditions(
  conditions: Record<string, unknown>
): { key: string; value: string }[] {
  return Object.entries(conditions).map(([key, value]) => {
    const formattedKey = key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
    const formattedValue =
      typeof value === 'object' && value !== null
        ? JSON.stringify(value, null, 2)
        : String(value);
    return { key: formattedKey, value: formattedValue };
  });
}

/**
 * Section wrapper for consistent spacing and titles
 */
function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon?: typeof TrendingUp;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        {title}
      </h3>
      {children}
    </div>
  );
}

/**
 * PatternDetailDrawer - Right-side sheet showing full details of a knowledge pattern
 */
export function PatternDetailDrawer({
  pattern,
  open,
  onOpenChange,
}: PatternDetailDrawerProps) {
  if (!pattern) return null;

  const typeConfig = patternTypeConfig[pattern.pattern_type];
  const TypeIcon = typeConfig.icon;

  const lifecycleConfig = pattern.lifecycle_status
    ? lifecycleStatusConfig[pattern.lifecycle_status.toLowerCase()]
    : null;

  const triggerConditions = formatTriggerConditions(pattern.trigger_conditions);
  const hasMarketConditions =
    pattern.market_conditions &&
    Object.keys(pattern.market_conditions).length > 0;
  const marketConditions = hasMarketConditions
    ? formatMarketConditions(pattern.market_conditions!)
    : [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-[480px] p-0 flex flex-col"
      >
        {/* Header */}
        <SheetHeader className="p-6 pb-4 space-y-0">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0 space-y-2">
              {/* Type Badge */}
              <div className="flex items-center gap-2 flex-wrap">
                <Badge className={`${typeConfig.color} text-white`}>
                  <TypeIcon className="w-3.5 h-3.5 mr-1" />
                  {typeConfig.label}
                </Badge>
                {lifecycleConfig && (
                  <Badge
                    variant="outline"
                    className={lifecycleConfig.color}
                  >
                    {lifecycleConfig.label}
                  </Badge>
                )}
                {!pattern.is_active && (
                  <Badge variant="outline" className="text-yellow-600 border-yellow-500/30">
                    Inactive
                  </Badge>
                )}
              </div>

              {/* Pattern Title */}
              <SheetTitle className="text-lg leading-tight">
                {pattern.pattern_name}
              </SheetTitle>
            </div>

            {/* Success Rate Ring */}
            <SuccessRateRing rate={pattern.success_rate} size={64} />
          </div>
          <SheetDescription className="sr-only">
            Details for pattern: {pattern.pattern_name}
          </SheetDescription>
        </SheetHeader>

        <Separator />

        {/* Scrollable Content */}
        <ScrollArea className="flex-1 overflow-hidden">
          <div className="p-6 space-y-6">
            {/* Trading Action / Expected Outcome */}
            <Section title="What to Do" icon={Target}>
              <div className="rounded-lg bg-primary/5 border border-primary/10 p-4">
                <p className="text-base font-semibold leading-relaxed text-foreground">
                  {pattern.expected_outcome}
                </p>
              </div>
            </Section>

            {/* Description */}
            <Section title="Description">
              <p className="text-sm text-muted-foreground leading-relaxed">
                {pattern.description}
              </p>
            </Section>

            {/* Trigger Conditions */}
            {triggerConditions.length > 0 && (
              <Section title="Trigger Conditions" icon={Zap}>
                <div className="space-y-2">
                  {triggerConditions.map(({ key, value }) => (
                    <div
                      key={key}
                      className="flex items-start gap-2 rounded-md bg-muted/50 px-3 py-2"
                    >
                      <span className="text-xs font-medium text-muted-foreground whitespace-nowrap mt-0.5">
                        {key}
                      </span>
                      <span className="text-sm text-foreground break-words">
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Market Conditions */}
            {hasMarketConditions && (
              <Section title="Market Conditions" icon={BarChart3}>
                <div className="space-y-2">
                  {marketConditions.map(({ key, value }) => (
                    <div
                      key={key}
                      className="flex items-start gap-2 rounded-md bg-muted/50 px-3 py-2"
                    >
                      <span className="text-xs font-medium text-muted-foreground whitespace-nowrap mt-0.5">
                        {key}
                      </span>
                      <span className="text-sm text-foreground break-words font-mono">
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Performance Stats */}
            <Section title="Performance Stats" icon={BarChart3}>
              <div className="grid grid-cols-2 gap-3">
                {/* Success Rate */}
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                    <CheckCircle className="h-3.5 w-3.5" />
                    Success Rate
                  </div>
                  <div className="text-lg font-bold">
                    {Math.round(pattern.success_rate * 100)}%
                  </div>
                  <div className="h-1.5 mt-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        pattern.success_rate >= 0.7
                          ? 'bg-green-500'
                          : pattern.success_rate >= 0.5
                            ? 'bg-amber-500'
                            : 'bg-red-500'
                      )}
                      style={{ width: `${pattern.success_rate * 100}%` }}
                    />
                  </div>
                </div>

                {/* Occurrences */}
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                    <Hash className="h-3.5 w-3.5" />
                    Occurrences
                  </div>
                  <div className="text-lg font-bold">
                    {pattern.occurrences}
                  </div>
                </div>

                {/* Successful Outcomes */}
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                    <Target className="h-3.5 w-3.5" />
                    Successful
                  </div>
                  <div className="text-lg font-bold">
                    {pattern.successful_outcomes}
                    <span className="text-sm font-normal text-muted-foreground">
                      {' '}
                      / {pattern.occurrences}
                    </span>
                  </div>
                </div>

                {/* Avg Return */}
                {pattern.avg_return_when_triggered !== undefined &&
                  pattern.avg_return_when_triggered !== null && (
                    <div className="rounded-lg bg-muted/50 p-3">
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1">
                        <TrendingUp className="h-3.5 w-3.5" />
                        Avg Return
                      </div>
                      <div
                        className={cn(
                          'text-lg font-bold',
                          pattern.avg_return_when_triggered >= 0
                            ? 'text-green-600 dark:text-green-400'
                            : 'text-red-600 dark:text-red-400'
                        )}
                      >
                        {pattern.avg_return_when_triggered >= 0 ? '+' : ''}
                        {(pattern.avg_return_when_triggered * 100).toFixed(2)}%
                      </div>
                    </div>
                  )}
              </div>

              {/* Date Stats */}
              <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
                {pattern.created_at && (
                  <div className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    <span>First seen: {formatDate(pattern.created_at)}</span>
                  </div>
                )}
                {pattern.last_triggered_at && (
                  <div className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    <span>Last seen: {formatDate(pattern.last_triggered_at)}</span>
                  </div>
                )}
              </div>
            </Section>

            {/* Related Symbols */}
            {pattern.related_symbols && pattern.related_symbols.length > 0 && (
              <Section title="Related Symbols" icon={TrendingUp}>
                <div className="flex flex-wrap gap-2">
                  {pattern.related_symbols.map((symbol) => (
                    <Badge
                      key={symbol}
                      variant="outline"
                      className="cursor-pointer hover:bg-primary/10 transition-colors"
                    >
                      {symbol}
                    </Badge>
                  ))}
                </div>
              </Section>
            )}

            {/* Related Sectors */}
            {pattern.related_sectors && pattern.related_sectors.length > 0 && (
              <Section title="Related Sectors">
                <div className="flex flex-wrap gap-2">
                  {pattern.related_sectors.map((sector, idx) => (
                    <Badge
                      key={sector}
                      variant="outline"
                      className={sectorColors[idx % sectorColors.length]}
                    >
                      {sector}
                    </Badge>
                  ))}
                </div>
              </Section>
            )}

            {/* Source Insights */}
            {pattern.source_insights &&
              pattern.source_insights.length > 0 && (
                <Section title="Source Insights" icon={ExternalLink}>
                  <div className="space-y-1.5">
                    {pattern.source_insights.map((insightId) => (
                      <Link
                        key={insightId}
                        href="/insights"
                        className="flex items-center gap-2 text-sm text-primary hover:underline"
                      >
                        <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                        <span className="truncate font-mono text-xs">
                          {insightId}
                        </span>
                      </Link>
                    ))}
                  </div>
                </Section>
              )}

            {/* Extraction Source (fallback if no source_insights) */}
            {pattern.extraction_source &&
              (!pattern.source_insights ||
                pattern.source_insights.length === 0) && (
                <Section title="Extraction Source" icon={ExternalLink}>
                  <p className="text-sm text-muted-foreground">
                    {pattern.extraction_source}
                  </p>
                </Section>
              )}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  );
}
