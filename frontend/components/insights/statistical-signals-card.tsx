'use client';

import { useState, useMemo } from 'react';
import {
  Activity,
  TrendingUp,
  TrendingDown,
  Minus,
  ChevronDown,
  ChevronUp,
  Filter,
  BarChart3,
  Zap,
  Calendar,
  CircleDot,
  Circle,
  CircleDashed,
  X,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import {
  useStatisticalFeatures,
  useActiveSignals,
  type StatisticalFeature,
  type ActiveSignal,
  type SignalStrength,
} from '@/lib/hooks/use-statistical-features';

// Props interface
interface StatisticalSignalsCardProps {
  symbol?: string; // If provided, show signals for specific symbol
  showAll?: boolean; // If true, show all active signals across watchlist
  maxSignals?: number; // Limit number of signals shown (default 10)
  className?: string;
  onClose?: () => void; // Callback when close button is clicked
}

// Signal type to color mapping
type SignalType = 'bullish' | 'bearish' | 'oversold' | 'overbought' | 'neutral' | 'elevated' | 'uptrend' | 'downtrend';

const signalColors: Record<string, { bg: string; text: string; border: string }> = {
  bullish: { bg: 'bg-green-500/10', text: 'text-green-600', border: 'border-green-500' },
  oversold: { bg: 'bg-green-500/10', text: 'text-green-600', border: 'border-green-500' },
  uptrend: { bg: 'bg-green-500/10', text: 'text-green-600', border: 'border-green-500' },
  bearish: { bg: 'bg-red-500/10', text: 'text-red-600', border: 'border-red-500' },
  overbought: { bg: 'bg-red-500/10', text: 'text-red-600', border: 'border-red-500' },
  downtrend: { bg: 'bg-red-500/10', text: 'text-red-600', border: 'border-red-500' },
  neutral: { bg: 'bg-yellow-500/10', text: 'text-yellow-600', border: 'border-yellow-500' },
  elevated: { bg: 'bg-yellow-500/10', text: 'text-yellow-600', border: 'border-yellow-500' },
};

const defaultSignalColor = { bg: 'bg-muted', text: 'text-muted-foreground', border: 'border-muted' };

// Get signal color based on signal string
function getSignalColor(signal: string) {
  const lowerSignal = signal.toLowerCase();
  return signalColors[lowerSignal] || defaultSignalColor;
}

// Get signal icon
function getSignalIcon(signal: string) {
  const lowerSignal = signal.toLowerCase();
  const iconClass = 'h-3 w-3';

  if (['bullish', 'oversold', 'uptrend'].includes(lowerSignal)) {
    return <TrendingUp className={cn(iconClass, 'text-green-600')} />;
  }
  if (['bearish', 'overbought', 'downtrend'].includes(lowerSignal)) {
    return <TrendingDown className={cn(iconClass, 'text-red-600')} />;
  }
  return <Minus className={cn(iconClass, 'text-yellow-600')} />;
}

// Strength indicator component
function StrengthIndicator({ strength }: { strength: SignalStrength }) {
  const iconClass = 'h-4 w-4';

  switch (strength) {
    case 'strong':
      return (
        <div className="flex items-center gap-1 text-green-600">
          <CircleDot className={iconClass} />
          <span className="text-xs font-medium">Strong</span>
        </div>
      );
    case 'moderate':
      return (
        <div className="flex items-center gap-1 text-yellow-600">
          <Circle className={iconClass} />
          <span className="text-xs font-medium">Moderate</span>
        </div>
      );
    case 'weak':
      return (
        <div className="flex items-center gap-1 text-muted-foreground">
          <CircleDashed className={iconClass} />
          <span className="text-xs font-medium">Weak</span>
        </div>
      );
    default:
      return null;
  }
}

// Feature type category mapping
const featureCategories: Record<string, { label: string; icon: typeof Activity }> = {
  momentum: { label: 'Momentum', icon: Zap },
  roc: { label: 'Momentum', icon: Zap },
  rsi: { label: 'Momentum', icon: Zap },
  zscore: { label: 'Mean Reversion', icon: BarChart3 },
  'z-score': { label: 'Mean Reversion', icon: BarChart3 },
  bollinger: { label: 'Mean Reversion', icon: BarChart3 },
  mean_reversion: { label: 'Mean Reversion', icon: BarChart3 },
  volatility: { label: 'Volatility', icon: Activity },
  regime: { label: 'Volatility', icon: Activity },
  percentile: { label: 'Volatility', icon: Activity },
  seasonality: { label: 'Seasonality', icon: Calendar },
  day_effect: { label: 'Seasonality', icon: Calendar },
  month_effect: { label: 'Seasonality', icon: Calendar },
  trend: { label: 'Trend', icon: TrendingUp },
};

// Get feature category
function getFeatureCategory(featureType: string) {
  const lowerType = featureType.toLowerCase();
  return featureCategories[lowerType] || { label: 'Other', icon: Activity };
}

// Signal item component
interface SignalItemProps {
  signal: ActiveSignal | StatisticalFeature;
  isExpanded: boolean;
  onToggle: () => void;
  showSymbol?: boolean;
}

function SignalItem({ signal, isExpanded, onToggle, showSymbol = true }: SignalItemProps) {
  const signalValue = 'signal' in signal ? signal.signal : 'neutral';
  const signalColor = getSignalColor(signalValue);
  const category = getFeatureCategory(signal.feature_type);
  const CategoryIcon = category.icon;
  const strength: SignalStrength = 'strength' in signal ? signal.strength : 'moderate';
  const percentile = 'percentile' in signal ? signal.percentile : undefined;

  return (
    <Collapsible open={isExpanded} onOpenChange={onToggle}>
      <CollapsibleTrigger asChild>
        <div
          className={cn(
            'flex items-center justify-between p-3 rounded-lg cursor-pointer transition-colors',
            'hover:bg-accent/50',
            'border',
            signalColor.border
          )}
        >
          <div className="flex items-center gap-3">
            <div className={cn('p-1.5 rounded-md', signalColor.bg)}>
              <CategoryIcon className={cn('h-4 w-4', signalColor.text)} />
            </div>

            <div>
              <div className="flex items-center gap-2">
                {showSymbol && (
                  <Badge variant="outline" className="font-mono text-xs">
                    {signal.symbol}
                  </Badge>
                )}
                <span className="text-sm font-medium capitalize">
                  {signal.feature_type.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                {getSignalIcon(signalValue)}
                <span className={cn('text-xs font-medium capitalize', signalColor.text)}>
                  {signalValue}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <StrengthIndicator strength={strength} />
            <div className="text-right">
              <div className="text-sm font-semibold">
                {typeof signal.value === 'number' ? signal.value.toFixed(2) : signal.value}
              </div>
              {percentile !== undefined && (
                <div className="text-xs text-muted-foreground">
                  {percentile}th percentile
                </div>
              )}
            </div>
            {isExpanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        </div>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="mt-2 ml-4 p-3 bg-muted/50 rounded-lg space-y-2">
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-muted-foreground">Category:</span>{' '}
              <span className="font-medium">{category.label}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Feature:</span>{' '}
              <span className="font-medium capitalize">
                {signal.feature_type.replace(/_/g, ' ')}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Signal:</span>{' '}
              <span className={cn('font-medium capitalize', signalColor.text)}>
                {signalValue}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Strength:</span>{' '}
              <span className="font-medium capitalize">{strength}</span>
            </div>
          </div>

          {percentile !== undefined && (
            <div className="pt-2">
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-muted-foreground">Percentile Rank</span>
                <span className="font-medium">{percentile}%</span>
              </div>
              <div className="h-2 w-full bg-secondary rounded-full overflow-hidden">
                <div
                  className={cn(
                    'h-full rounded-full transition-all',
                    percentile >= 80 && 'bg-green-500',
                    percentile >= 50 && percentile < 80 && 'bg-yellow-500',
                    percentile >= 20 && percentile < 50 && 'bg-orange-500',
                    percentile < 20 && 'bg-red-500'
                  )}
                  style={{ width: `${percentile}%` }}
                />
              </div>
            </div>
          )}

          {'calculation_date' in signal && signal.calculation_date && (
            <div className="text-xs text-muted-foreground pt-2">
              Calculated: {new Date(signal.calculation_date).toLocaleString()}
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

// Loading skeleton
function SignalsLoadingSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="flex items-center gap-3 p-3 border rounded-lg">
          <Skeleton className="h-8 w-8 rounded-md" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
          <Skeleton className="h-6 w-16" />
        </div>
      ))}
    </div>
  );
}

// Empty state
function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <Activity className="h-12 w-12 text-muted-foreground/50 mb-3" />
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

// Sort options
type SortOption = 'strength' | 'value' | 'symbol';

// Main component
export function StatisticalSignalsCard({
  symbol,
  showAll = false,
  maxSignals = 10,
  className,
  onClose,
}: StatisticalSignalsCardProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [signalFilter, setSignalFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<SortOption>('strength');

  // Fetch data based on props
  const symbolFeatures = useStatisticalFeatures(symbol || '');
  const activeSignals = useActiveSignals(
    showAll && signalFilter !== 'all' ? { signalType: signalFilter } : undefined
  );

  // Determine which data to use
  const isLoading = symbol ? symbolFeatures.isLoading : activeSignals.isLoading;
  const isError = symbol ? symbolFeatures.isError : activeSignals.isError;

  // Convert features to signal format for unified handling
  const symbolFeaturesData = symbolFeatures?.features;
  const activeSignalsData = activeSignals?.signals;

  const signals = useMemo(() => {
    if (symbol && symbolFeaturesData?.length) {
      return symbolFeaturesData.map((f) => ({
        ...f,
        strength: ('strength' in f ? f.strength : 'moderate') as SignalStrength,
      }));
    }
    if (symbol) {
      return []; // Return empty array if no features data for symbol
    }
    return activeSignalsData ?? [];
  }, [symbol, symbolFeaturesData, activeSignalsData]);

  // Static list of all available signal types for the filter dropdown
  const allSignalTypes: SignalType[] = [
    'bullish',
    'bearish',
    'oversold',
    'overbought',
    'neutral',
    'elevated',
    'uptrend',
    'downtrend',
  ];

  // Filter signals
  const filteredSignals = useMemo(() => {
    let result = [...signals];

    // Apply signal type filter
    if (signalFilter !== 'all') {
      result = result.filter((s) => s.signal === signalFilter);
    }

    // Apply sorting
    result.sort((a, b) => {
      if (sortBy === 'strength') {
        const strengthOrder: Record<SignalStrength, number> = { strong: 3, moderate: 2, weak: 1 };
        const aStrength = 'strength' in a ? strengthOrder[a.strength] : 2;
        const bStrength = 'strength' in b ? strengthOrder[b.strength] : 2;
        return bStrength - aStrength;
      }
      if (sortBy === 'value') {
        return Math.abs(b.value) - Math.abs(a.value);
      }
      if (sortBy === 'symbol') {
        return a.symbol.localeCompare(b.symbol);
      }
      return 0;
    });

    // Limit results
    return result.slice(0, maxSignals);
  }, [signals, signalFilter, sortBy, maxSignals]);

  // Toggle expanded state
  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  // Get signal ID
  const getSignalId = (signal: ActiveSignal | StatisticalFeature, index: number) => {
    if ('id' in signal) return signal.id;
    return `${signal.symbol}-${signal.feature_type}-${index}`;
  };

  return (
    <Card className={cn('', className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-primary/10">
              <Activity className="h-5 w-5 text-primary" />
            </div>
            <CardTitle className="text-lg">
              Statistical Signals
              {symbol && <span className="text-muted-foreground ml-1">({symbol})</span>}
            </CardTitle>
          </div>

          <div className="flex items-center gap-2">
            {!isLoading && signals.length > 0 && (
              <Badge variant="secondary" className="font-mono">
                {filteredSignals.length} / {signals.length}
              </Badge>
            )}
            {onClose && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={onClose}
                aria-label="Close signals panel"
              >
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Filters - Always visible when not loading */}
        {!isLoading && (
          <div className="flex items-center gap-2 mb-4">
            <Select value={signalFilter} onValueChange={setSignalFilter}>
              <SelectTrigger className="w-[140px] h-8">
                <Filter className="h-3 w-3 mr-1" />
                <SelectValue placeholder="Filter signals" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Signals</SelectItem>
                {allSignalTypes.map((type) => (
                  <SelectItem key={type} value={type} className="capitalize">
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={sortBy} onValueChange={(v) => setSortBy(v as SortOption)}>
              <SelectTrigger className="w-[120px] h-8">
                <SelectValue placeholder="Sort by" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="strength">Strength</SelectItem>
                <SelectItem value="value">Value</SelectItem>
                <SelectItem value="symbol">Symbol</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Loading state */}
        {isLoading && <SignalsLoadingSkeleton />}

        {/* Error state */}
        {isError && (
          <EmptyState message="Failed to load signals. Please try again." />
        )}

        {/* Empty state */}
        {!isLoading && !isError && filteredSignals.length === 0 && (
          <EmptyState
            message={
              signalFilter !== 'all'
                ? `No ${signalFilter} signals found`
                : symbol
                ? `No signals for ${symbol}`
                : 'No active signals in your watchlist'
            }
          />
        )}

        {/* Signals list */}
        {!isLoading && !isError && filteredSignals.length > 0 && (
          <div className="space-y-2">
            {filteredSignals.map((signal, index) => {
              const id = getSignalId(signal, index);
              return (
                <SignalItem
                  key={id}
                  signal={signal}
                  isExpanded={expandedIds.has(id)}
                  onToggle={() => toggleExpanded(id)}
                  showSymbol={showAll || !symbol}
                />
              );
            })}
          </div>
        )}

        {/* Show more indicator */}
        {!isLoading && signals.length > maxSignals && (
          <div className="mt-4 text-center">
            <Button variant="ghost" size="sm" className="text-muted-foreground">
              {signals.length - maxSignals} more signals available
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
