'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  Clock,
  Target,
  Shield,
  History,
  Users,
  CalendarClock,
  RefreshCw,
  Plus,
  MessageSquare,
  ChevronRight,
  ChevronDown,
  ArrowLeft,
  Loader2,
  Database,
  Briefcase,
  BarChart3,
  Activity,
  Globe,
  MessageCircle,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
} from 'recharts';
import { InsightConversationPanel } from '@/components/insights/insight-conversation-panel';
import { StatisticalSignalsCard } from '@/components/insights/statistical-signals-card';
import { OutcomeBadge } from '@/components/insights/outcome-badge';
import { DiscoveryContextCard } from '@/components/insights/discovery-context-card';
import { useDeepInsight, deepInsightKeys } from '@/lib/hooks/use-deep-insights';
import {
  useInsightConversations,
  type InsightConversation,
} from '@/lib/hooks/use-insight-conversation';
import { usePortfolio } from '@/lib/hooks/use-portfolio';
import type { DeepInsight, InsightAction } from '@/types';

// ============================================
// Types
// ============================================

interface InsightDetailViewProps {
  insightId: number;
}

// ============================================
// Action Config (matching deep-insight-card.tsx)
// ============================================

const actionConfig: Record<InsightAction, { color: string; icon: typeof TrendingUp; label: string; bgColor: string }> = {
  STRONG_BUY: { color: 'bg-green-600', icon: TrendingUp, label: 'Strong Buy', bgColor: 'bg-green-600/10' },
  BUY: { color: 'bg-green-500', icon: TrendingUp, label: 'Buy', bgColor: 'bg-green-500/10' },
  HOLD: { color: 'bg-yellow-500', icon: Minus, label: 'Hold', bgColor: 'bg-yellow-500/10' },
  SELL: { color: 'bg-red-500', icon: TrendingDown, label: 'Sell', bgColor: 'bg-red-500/10' },
  STRONG_SELL: { color: 'bg-red-600', icon: TrendingDown, label: 'Strong Sell', bgColor: 'bg-red-600/10' },
  WATCH: { color: 'bg-blue-500', icon: Target, label: 'Watch', bgColor: 'bg-blue-500/10' },
};

// ============================================
// Helper Functions
// ============================================

/**
 * Format a timestamp into a full, explicit date/time string
 * Output format: "Feb 1, 2026, 3:30 PM EST"
 */
function formatInsightDate(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  });
}

// ============================================
// Sub-Components
// ============================================

function ConfidenceIndicator({ confidence }: { confidence: number }) {
  const percentage = Math.round(confidence * 100);
  const getColor = () => {
    if (percentage >= 80) return 'text-green-600 bg-green-100 dark:bg-green-900/30';
    if (percentage >= 60) return 'text-yellow-600 bg-yellow-100 dark:bg-yellow-900/30';
    return 'text-red-600 bg-red-100 dark:bg-red-900/30';
  };

  return (
    <div className={cn('rounded-lg px-4 py-3 text-center', getColor())}>
      <div className="text-3xl font-bold">{percentage}%</div>
      <div className="text-xs font-medium uppercase tracking-wide opacity-80">Confidence</div>
    </div>
  );
}

function ConversationListItem({
  conversation,
  isActive,
  onClick,
}: {
  conversation: InsightConversation;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors',
        isActive
          ? 'bg-primary/10 text-primary'
          : 'hover:bg-muted/50 text-muted-foreground hover:text-foreground'
      )}
    >
      <MessageSquare className="h-4 w-4 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{conversation.title}</p>
        <p className="text-xs text-muted-foreground">
          {formatDistanceToNow(new Date(conversation.updated_at), { addSuffix: true })}
        </p>
      </div>
      {isActive && <ChevronRight className="h-4 w-4 flex-shrink-0" />}
    </button>
  );
}

function InsightDetailsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-6">
        <Skeleton className="h-16 w-32" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
        <Skeleton className="h-16 w-24" />
      </div>
      <Skeleton className="h-px w-full" />
      <div className="space-y-4">
        <Skeleton className="h-4 w-32" />
        <div className="flex gap-2">
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-6 w-16" />
          <Skeleton className="h-6 w-16" />
        </div>
      </div>
      <Skeleton className="h-px w-full" />
      <div className="space-y-4">
        <Skeleton className="h-4 w-40" />
        <div className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      </div>
    </div>
  );
}

// ============================================
// Analysis Dimension Helpers
// ============================================

const TA_RATING_STYLES: Record<string, string> = {
  'strong buy': 'bg-green-600 text-white',
  'buy': 'bg-green-500 text-white',
  'neutral': 'bg-gray-500 text-white',
  'sell': 'bg-orange-500 text-white',
  'strong sell': 'bg-red-600 text-white',
};

/** Plain-English explanations for the overall composite rating */
const RATING_EXPLANATIONS: Record<string, string> = {
  'strong buy': 'Strong bullish signal -- multiple indicators align upward',
  'buy': 'Moderately bullish -- more indicators point up than down',
  'neutral': 'Mixed signals -- no clear direction from indicators',
  'sell': 'Moderately bearish -- more indicators point down than up',
  'strong sell': 'Strong bearish signal -- multiple indicators align downward',
};

/** Map a breakdown value (-1..+1) to a human-readable label, arrow, and explanation */
function describeBreakdownValue(
  dimension: 'trend' | 'momentum' | 'volatility' | 'volume',
  value: number,
): { label: string; arrow: string; color: string; explanation: string } {
  // Volatility is special: high volatility is not inherently good or bad
  const isVolatility = dimension === 'volatility';

  if (value > 0.6) {
    if (isVolatility) return { label: 'Very High', arrow: '!!', color: 'text-amber-500', explanation: 'Price swings are much larger than normal -- expect significant moves' };
    return { label: 'Strong', arrow: '^^', color: 'text-green-500', explanation: getDimensionExplanation(dimension, 'strong') };
  }
  if (value > 0.2) {
    if (isVolatility) return { label: 'Elevated', arrow: '!', color: 'text-amber-400', explanation: 'Price swings are larger than normal -- expect bigger moves' };
    return { label: 'Moderate', arrow: '^', color: 'text-green-400', explanation: getDimensionExplanation(dimension, 'moderate') };
  }
  if (value >= -0.2) {
    if (isVolatility) return { label: 'Normal', arrow: '', color: 'text-muted-foreground', explanation: 'Price swings are at typical levels' };
    return { label: 'Neutral', arrow: '-', color: 'text-muted-foreground', explanation: getDimensionExplanation(dimension, 'neutral') };
  }
  if (value >= -0.6) {
    if (isVolatility) return { label: 'Low', arrow: '', color: 'text-blue-400', explanation: 'Price is relatively calm with small moves' };
    return { label: 'Weak', arrow: 'v', color: 'text-red-400', explanation: getDimensionExplanation(dimension, 'weak') };
  }
  if (isVolatility) return { label: 'Very Low', arrow: '', color: 'text-blue-500', explanation: 'Unusually calm -- price barely moving' };
  return { label: 'Very Weak', arrow: 'vv', color: 'text-red-500', explanation: getDimensionExplanation(dimension, 'very_weak') };
}

function getDimensionExplanation(
  dimension: 'trend' | 'momentum' | 'volume',
  strength: 'strong' | 'moderate' | 'neutral' | 'weak' | 'very_weak',
): string {
  const explanations: Record<string, Record<string, string>> = {
    trend: {
      strong: 'Price is consistently moving higher, supported by moving averages',
      moderate: 'Price is trending upward with some support from indicators',
      neutral: 'Price direction is unclear -- moving sideways',
      weak: 'Price is drifting lower with weakening support',
      very_weak: 'Price is in a clear downtrend across multiple timeframes',
    },
    momentum: {
      strong: 'Strong buying pressure is pushing prices higher',
      moderate: 'Buying pressure is slightly above average',
      neutral: 'Neither buyers nor sellers have a clear edge',
      weak: 'Selling pressure is building up',
      very_weak: 'Heavy selling pressure is driving prices down',
    },
    volume: {
      strong: 'Trading activity is unusually high -- strong conviction behind moves',
      moderate: 'Trading activity is above average',
      neutral: 'Trading activity is at typical levels',
      weak: 'Trading activity is below average -- less conviction',
      very_weak: 'Very low trading activity -- moves may not be sustainable',
    },
  };
  return explanations[dimension]?.[strength] ?? '';
}

function getRatingBadgeClass(rating: string): string {
  return TA_RATING_STYLES[rating.toLowerCase()] ?? 'bg-gray-500 text-white';
}

function getMoodBadgeClass(mood: string): string {
  const lower = mood.toLowerCase();
  if (lower.includes('very bullish')) return 'bg-green-600 text-white';
  if (lower.includes('bullish')) return 'bg-green-500 text-white';
  if (lower.includes('very bearish')) return 'bg-red-600 text-white';
  if (lower.includes('bearish')) return 'bg-red-500 text-white';
  return 'bg-gray-500 text-white';
}

function getMoodEmoji(mood: string): string {
  const lower = mood.toLowerCase();
  if (lower.includes('very bullish')) return '🟢';
  if (lower.includes('bullish')) return '🟢';
  if (lower.includes('very bearish')) return '🔴';
  if (lower.includes('bearish')) return '🔴';
  return '⚪';
}

function getMoodExplanation(mood: string): string {
  const lower = mood.toLowerCase();
  if (lower.includes('very bullish')) return 'Reddit communities are very optimistic about the market';
  if (lower.includes('bullish')) return 'Social sentiment is generally positive';
  if (lower.includes('very bearish')) return 'Reddit communities are highly pessimistic';
  if (lower.includes('bearish')) return 'Social sentiment is cautious';
  return 'Mixed opinions across trading communities';
}

/** Normalize a -1..+1 value to 0..1 for the radar chart */
function normalizeForRadar(value: number): number {
  return Math.max(0, Math.min(1, (value + 1) / 2));
}

/** Describe a fed rate probability in plain English */
function describeFedAction(action: string, prob: number): string {
  const pct = Math.round(prob * 100);
  const lower = action.toLowerCase();
  if (lower.includes('cut')) {
    if (pct < 5) return 'Markets see almost no chance of a rate cut';
    if (pct < 30) return 'A rate cut is unlikely but not ruled out';
    if (pct < 60) return 'Markets see a moderate chance of a rate cut';
    return 'Markets are pricing in a rate cut';
  }
  if (lower.includes('hike') || lower.includes('raise')) {
    if (pct < 5) return 'Markets see almost no chance of a rate hike';
    if (pct < 30) return 'A rate hike is unlikely but possible';
    return 'Markets are pricing in a rate hike';
  }
  if (lower.includes('hold') || lower.includes('no change') || lower.includes('unchanged')) {
    if (pct > 80) return 'Markets overwhelmingly expect rates to stay unchanged';
    if (pct > 50) return 'Markets mostly expect rates to stay unchanged';
    return 'Mixed expectations on whether rates will change';
  }
  return `${pct}% probability`;
}

// ============================================
// Analysis Dimensions Sub-Components
// ============================================

/** Horizontal bar with gradient fill for a breakdown dimension */
function DimensionBar({
  dimension,
  value,
}: {
  dimension: 'trend' | 'momentum' | 'volatility' | 'volume';
  value: number;
}) {
  const info = describeBreakdownValue(dimension, value);
  // Bar fill: normalize -1..+1 to 0%..100%
  const fillPct = Math.round((value + 1) * 50);
  const isPositive = value >= 0;

  const dimensionLabels: Record<string, string> = {
    trend: 'Trend',
    momentum: 'Momentum',
    volatility: 'Volatility',
    volume: 'Volume',
  };

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-3 py-1.5 cursor-help group">
          <div className="w-24 shrink-0">
            <span className="text-sm font-medium text-foreground">{dimensionLabels[dimension]}</span>
          </div>
          <div className="flex-1 space-y-1">
            <div className="flex items-center justify-between">
              <span className={cn('text-xs font-medium', info.color)}>
                {info.label} {info.arrow}
              </span>
              <span className="text-xs font-mono text-muted-foreground">
                {Math.round(fillPct)}%
              </span>
            </div>
            <div className="h-2.5 rounded-full bg-muted relative overflow-hidden">
              {/* Center line */}
              <div className="absolute left-1/2 top-0 h-full w-px bg-muted-foreground/20 z-10" />
              {/* Value bar from center */}
              <div
                className={cn(
                  'absolute top-0 h-full rounded-full transition-all duration-500',
                  dimension === 'volatility'
                    ? 'bg-gradient-to-r from-amber-400 to-amber-500'
                    : isPositive
                      ? 'bg-gradient-to-r from-green-400 to-green-500'
                      : 'bg-gradient-to-r from-red-500 to-red-400'
                )}
                style={
                  isPositive
                    ? { left: '50%', width: `${value * 50}%` }
                    : { left: `${50 + value * 50}%`, width: `${Math.abs(value) * 50}%` }
                }
              />
            </div>
          </div>
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs">
        <p>{info.explanation}</p>
      </TooltipContent>
    </Tooltip>
  );
}

/** Probability bar for prediction market data */
function ProbabilityBar({
  label,
  probability,
  source,
}: {
  label: string;
  probability: number;
  source?: string;
}) {
  const pct = Math.round(probability * 100);
  const barColor =
    pct >= 70 ? 'bg-green-500' :
    pct >= 40 ? 'bg-amber-500' :
    pct >= 15 ? 'bg-orange-500' : 'bg-red-500';

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-foreground">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-sm font-mono font-semibold text-foreground">{pct}%</span>
          {source && (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">{source}</Badge>
          )}
        </div>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-500', barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** Radar chart for the 4 TA dimensions */
function TARadarChart({
  breakdown,
}: {
  breakdown: { trend: number; momentum: number; volatility: number; volume: number };
}) {
  const data = [
    { dimension: 'Trend', value: normalizeForRadar(breakdown.trend) },
    { dimension: 'Momentum', value: normalizeForRadar(breakdown.momentum) },
    { dimension: 'Volatility', value: normalizeForRadar(breakdown.volatility) },
    { dimension: 'Volume', value: normalizeForRadar(breakdown.volume) },
  ];

  return (
    <ResponsiveContainer width="100%" height={200}>
      <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
        <PolarGrid stroke="hsl(var(--muted-foreground))" strokeOpacity={0.2} />
        <PolarAngleAxis
          dataKey="dimension"
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 1]}
          tick={false}
          axisLine={false}
        />
        <Radar
          name="Signal"
          dataKey="value"
          stroke="hsl(var(--primary))"
          fill="hsl(var(--primary))"
          fillOpacity={0.2}
          strokeWidth={2}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}

// ============================================
// Analysis Dimensions Section
// ============================================

function AnalysisDimensionsSection({ insight }: { insight: DeepInsight }) {
  const ta = insight.technical_analysis_data;
  const pred = insight.prediction_market_data;
  const sent = insight.sentiment_data;

  // Bail out completely if no data
  if (!ta && !pred && !sent) return null;

  const ratingExplanation = ta
    ? RATING_EXPLANATIONS[ta.rating.toLowerCase()] ?? 'Technical indicators have been evaluated'
    : '';

  return (
    <Collapsible>
      <CollapsibleTrigger className="flex items-center gap-2 w-full py-2 group">
        <BarChart3 className="h-4 w-4" />
        <span className="text-sm font-semibold">Analysis Dimensions</span>
        <ChevronDown className="h-4 w-4 ml-auto transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-4 pt-3">

        {/* ---- Technical Analysis Card ---- */}
        {ta && (
          <div className="rounded-xl border border-border/50 bg-slate-800/30 dark:bg-slate-800/50 overflow-hidden">
            {/* Card header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border/30 bg-slate-800/20">
              <Activity className="h-4 w-4 text-blue-400" />
              <span className="text-sm font-semibold text-foreground">Technical Analysis</span>
            </div>

            <div className="p-4 space-y-4">
              {/* Overall signal row */}
              <div className="flex items-start gap-3 flex-wrap">
                <Badge className={cn('text-sm px-4 py-1.5 font-semibold', getRatingBadgeClass(ta.rating))}>
                  {ta.rating}
                </Badge>
                <div className="flex-1 min-w-[200px]">
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-sm text-muted-foreground">
                      Confidence: <span className="font-semibold text-foreground">{Math.round(ta.confidence * 100)}%</span>
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">{ratingExplanation}</p>
                </div>
              </div>

              {/* Radar chart + dimension bars in a two-column layout */}
              {ta.breakdown && (
                <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 items-start">
                  {/* Radar chart */}
                  <div className="flex justify-center">
                    <TARadarChart breakdown={ta.breakdown} />
                  </div>

                  {/* Dimension bars */}
                  <div className="space-y-1">
                    <DimensionBar dimension="trend" value={ta.breakdown.trend} />
                    <DimensionBar dimension="momentum" value={ta.breakdown.momentum} />
                    <DimensionBar dimension="volatility" value={ta.breakdown.volatility} />
                    <DimensionBar dimension="volume" value={ta.breakdown.volume} />
                  </div>
                </div>
              )}

              {/* Key price levels */}
              {ta.key_levels && (
                <div className="rounded-lg bg-muted/30 px-4 py-3">
                  <span className="text-xs font-medium text-muted-foreground block mb-2">
                    Key price levels to watch
                  </span>
                  <div className="flex flex-wrap gap-4 text-sm">
                    {ta.key_levels.support.length > 0 && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-1.5 cursor-help">
                            <Shield className="h-3.5 w-3.5 text-green-500" />
                            <span className="text-muted-foreground">Support (floor):</span>
                            <span className="font-mono font-semibold text-green-500">
                              {ta.key_levels.support.map((l) => `$${l.toLocaleString()}`).join(', ')}
                            </span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Price levels where buying tends to increase, preventing further drops</TooltipContent>
                      </Tooltip>
                    )}
                    {ta.key_levels.resistance.length > 0 && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-1.5 cursor-help">
                            <Target className="h-3.5 w-3.5 text-red-500" />
                            <span className="text-muted-foreground">Resistance (ceiling):</span>
                            <span className="font-mono font-semibold text-red-500">
                              {ta.key_levels.resistance.map((l) => `$${l.toLocaleString()}`).join(', ')}
                            </span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Price levels where selling tends to increase, preventing further rises</TooltipContent>
                      </Tooltip>
                    )}
                    {ta.key_levels.pivot != null && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-1.5 cursor-help">
                            <span className="text-muted-foreground">Pivot:</span>
                            <span className="font-mono font-semibold text-foreground">
                              ${ta.key_levels.pivot.toLocaleString()}
                            </span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Central price level that may act as support or resistance</TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                </div>
              )}

              {/* Signals */}
              {ta.signals && ta.signals.length > 0 && (
                <div>
                  <span className="text-xs font-medium text-muted-foreground block mb-2">Active Signals</span>
                  <div className="flex flex-wrap gap-1.5">
                    {ta.signals.map((sig, i) => (
                      <Badge key={i} variant="outline" className="text-xs">
                        {sig}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ---- Prediction Markets Card ---- */}
        {pred && (
          <div className="rounded-xl border border-border/50 bg-slate-800/30 dark:bg-slate-800/50 overflow-hidden">
            {/* Card header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border/30 bg-slate-800/20">
              <Globe className="h-4 w-4 text-purple-400" />
              <span className="text-sm font-semibold text-foreground">Prediction Markets</span>
            </div>

            <div className="p-4 space-y-4">
              {/* Fed rate probabilities */}
              {pred.fed_rates?.next_meeting?.probabilities && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">Fed Rate Outlook</span>
                    {pred.fed_rates.next_meeting.date && (
                      <span className="text-xs text-muted-foreground">
                        Next meeting: {pred.fed_rates.next_meeting.date}
                      </span>
                    )}
                  </div>
                  {Object.entries(pred.fed_rates.next_meeting.probabilities).map(([action, prob]) => {
                    const probability = typeof prob === 'number' ? prob : 0;
                    return (
                      <div key={action} className="space-y-1">
                        <ProbabilityBar
                          label={action}
                          probability={probability}
                          source={pred.fed_rates?.source}
                        />
                        <p className="text-xs text-muted-foreground pl-1">
                          {describeFedAction(action, probability)}
                        </p>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Recession probability */}
              {pred.recession?.probability_2026 != null && (
                <ProbabilityBar
                  label="Recession Risk (2026)"
                  probability={pred.recession.probability_2026}
                  source={pred.recession.source}
                />
              )}

              {/* Inflation */}
              {pred.inflation?.cpi_above_3pct != null && (
                <ProbabilityBar
                  label="Inflation above 3%"
                  probability={pred.inflation.cpi_above_3pct}
                  source={pred.inflation.source}
                />
              )}

              {/* GDP */}
              {pred.gdp?.q1_positive != null && (
                <ProbabilityBar
                  label="Q1 GDP Growth (positive)"
                  probability={pred.gdp.q1_positive}
                  source={pred.gdp.source}
                />
              )}

              {/* S&P 500 targets */}
              {pred.sp500?.targets && pred.sp500.targets.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm font-medium text-foreground">S&P 500 Price Targets</span>
                    {pred.sp500.source && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">{pred.sp500.source}</Badge>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {pred.sp500.targets.map((t, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-1.5 text-sm rounded-lg border border-border/50 bg-background px-3 py-1.5"
                      >
                        <span className="font-mono font-semibold">{t.level.toLocaleString()}</span>
                        <span className="text-muted-foreground text-xs">
                          ({Math.round(t.probability * 100)}% chance)
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ---- Social Sentiment Card ---- */}
        {sent && (
          <div className="rounded-xl border border-border/50 bg-slate-800/30 dark:bg-slate-800/50 overflow-hidden">
            {/* Card header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-border/30 bg-slate-800/20">
              <MessageCircle className="h-4 w-4 text-orange-400" />
              <span className="text-sm font-semibold text-foreground">Social Sentiment</span>
            </div>

            <div className="p-4 space-y-4">
              {/* Overall mood */}
              {sent.overall_mood && (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground">Mood:</span>
                    <Badge className={cn('text-sm px-3 py-1', getMoodBadgeClass(sent.overall_mood))}>
                      {sent.overall_mood} {getMoodEmoji(sent.overall_mood)}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground pl-1">{getMoodExplanation(sent.overall_mood)}</p>
                </div>
              )}

              {/* Trending tickers */}
              {sent.trending && sent.trending.length > 0 && (
                <div>
                  <span className="text-xs font-medium text-muted-foreground block mb-2">
                    Trending on Social Media
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {sent.trending.map((item, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-1.5 text-sm rounded-lg border border-border/50 bg-background px-3 py-1.5 hover:bg-muted/50 transition-colors"
                      >
                        <span className="font-mono font-semibold">{item.ticker}</span>
                        <span className="text-xs text-muted-foreground">
                          {item.mentions} mentions
                        </span>
                        {item.upvotes != null && (
                          <span className="text-xs text-muted-foreground">
                            / {item.upvotes} upvotes
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Per-symbol sentiment */}
              {sent.per_symbol && sent.per_symbol.length > 0 && (
                <div>
                  <span className="text-xs font-medium text-muted-foreground block mb-2">
                    Sentiment by Symbol
                  </span>
                  <div className="space-y-2">
                    {sent.per_symbol.map((sym, i) => {
                      const isPositive = sym.sentiment_score >= 0;
                      const barPct = Math.round(Math.abs(sym.sentiment_score) * 100);
                      const barColor = sym.sentiment_score >= 0.3
                        ? 'bg-green-500'
                        : sym.sentiment_score <= -0.3
                          ? 'bg-red-500'
                          : 'bg-gray-400';
                      const sentimentLabel = sym.sentiment_score >= 0.3
                        ? 'Bullish'
                        : sym.sentiment_score <= -0.3
                          ? 'Bearish'
                          : 'Neutral';
                      return (
                        <div key={i} className="flex items-center gap-3 text-sm">
                          <span className="font-mono font-semibold w-16 shrink-0">{sym.symbol}</span>
                          <div className="flex-1">
                            <div className="h-2 rounded-full bg-muted overflow-hidden">
                              <div
                                className={cn('h-full rounded-full transition-all', barColor)}
                                style={{ width: `${Math.min(barPct, 100)}%` }}
                              />
                            </div>
                          </div>
                          <span className={cn(
                            'text-xs font-medium w-14 text-right',
                            isPositive ? 'text-green-500' : 'text-red-500'
                          )}>
                            {sentimentLabel}
                          </span>
                          <span className="text-xs text-muted-foreground w-20 text-right">
                            {sym.post_count} posts
                          </span>
                          {sym.bullish_count != null && sym.bearish_count != null && (
                            <span className="text-xs text-muted-foreground">
                              (<span className="text-green-500">{sym.bullish_count}</span>
                              {' / '}
                              <span className="text-red-500">{sym.bearish_count}</span>)
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

      </CollapsibleContent>
    </Collapsible>
  );
}

// ============================================
// Insight Details Panel
// ============================================

function InsightDetailsPanel({
  insight,
  onRefresh,
  isRefreshing,
  onSymbolClick,
  portfolioMatch,
}: {
  insight: DeepInsight;
  onRefresh: () => void;
  isRefreshing: boolean;
  onSymbolClick: (symbol: string) => void;
  portfolioMatch?: { symbols: string[]; allocationPct?: number } | null;
}) {
  const actionInfo = actionConfig[insight.action];
  const ActionIcon = actionInfo.icon;

  return (
    <div className="space-y-6">
      {/* Header Section */}
      <div className="flex flex-col lg:flex-row lg:items-start gap-4 lg:gap-6">
        {/* Action Badge - Large and Prominent */}
        <div className={cn('p-4 rounded-xl flex flex-col items-center justify-center min-w-[120px]', actionInfo.bgColor)}>
          <Badge className={cn('text-white text-sm px-4 py-2', actionInfo.color)}>
            <ActionIcon className="w-4 h-4 mr-2" />
            {actionInfo.label}
          </Badge>
        </div>

        {/* Title and Thesis */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2 mb-2">
            <h1 className="text-2xl font-bold tracking-tight">{insight.title}</h1>
            {portfolioMatch && portfolioMatch.symbols.length > 0 && (
              <Badge
                variant="outline"
                className="shrink-0 mt-1 border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300"
              >
                <Briefcase className="w-3 h-3" />
                In Portfolio
                {portfolioMatch.allocationPct != null && (
                  <span className="ml-0.5 opacity-80">
                    ({portfolioMatch.allocationPct.toFixed(1)}%)
                  </span>
                )}
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground leading-relaxed">{insight.thesis}</p>
        </div>

        {/* Confidence Score */}
        <ConfidenceIndicator confidence={insight.confidence} />

        {/* Outcome Badge for actionable insights */}
        {(insight.action === 'BUY' || insight.action === 'STRONG_BUY' ||
          insight.action === 'SELL' || insight.action === 'STRONG_SELL') && (
          <TooltipProvider>
            <OutcomeBadge
              insightId={insight.id}
              size="lg"
              showDetails={true}
            />
          </TooltipProvider>
        )}
      </div>

      <Separator />

      {/* Time and Symbols Section */}
      <div className="flex flex-wrap gap-6">
        {/* Time Horizon */}
        <div className="flex items-center gap-2">
          <Clock className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">{insight.time_horizon}</p>
            <p className="text-xs text-muted-foreground">Time Horizon</p>
          </div>
        </div>

        {/* Insight Type */}
        <div>
          <Badge variant="outline" className="capitalize">
            {insight.insight_type}
          </Badge>
          <p className="text-xs text-muted-foreground mt-1">Insight Type</p>
        </div>

        {/* Timestamps - Explicit Date/Time Display */}
        <div className="flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">
              {formatInsightDate(insight.created_at)}
            </p>
            <p className="text-xs text-muted-foreground">Analysis Date</p>
          </div>
        </div>

        {insight.updated_at && insight.updated_at !== insight.created_at && (
          <div className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">
                {formatInsightDate(insight.updated_at)}
              </p>
              <p className="text-xs text-muted-foreground">Last Updated</p>
            </div>
          </div>
        )}
      </div>

      <Separator />

      {/* Symbols Section */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Target className="h-4 w-4" /> Symbols
        </h3>
        <div className="flex flex-wrap gap-2">
          {insight.primary_symbol && (
            <Badge
              variant="default"
              className="cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => onSymbolClick(insight.primary_symbol!)}
            >
              {insight.primary_symbol}
              <span className="ml-1 text-xs opacity-70">Primary</span>
            </Badge>
          )}
          {insight.related_symbols.map((symbol) => (
            <Badge
              key={symbol}
              variant="secondary"
              className="cursor-pointer hover:bg-secondary/80 transition-colors"
              onClick={() => onSymbolClick(symbol)}
            >
              {symbol}
            </Badge>
          ))}
          {!insight.primary_symbol && insight.related_symbols.length === 0 && (
            <p className="text-sm text-muted-foreground">No specific symbols</p>
          )}
        </div>
      </div>

      {/* Statistical Signals for Primary Symbol */}
      {insight.primary_symbol && (
        <>
          <Separator />
          <StatisticalSignalsCard
            symbol={insight.primary_symbol}
            maxSignals={5}
            className="border-0 shadow-none p-0"
          />
        </>
      )}

      <Separator />

      {/* Supporting Evidence */}
      <div>
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Users className="h-4 w-4" /> Supporting Evidence from Analysts
        </h3>
        <div className="space-y-3">
          {insight.supporting_evidence.map((evidence, i) => (
            <Card key={i} className="bg-muted/30">
              <CardContent className="pt-4">
                <div className="flex items-start gap-3">
                  <Badge variant="outline" className="capitalize shrink-0">
                    {evidence.analyst}
                  </Badge>
                  <p className="text-sm text-muted-foreground flex-1">{evidence.finding}</p>
                  {evidence.confidence && (
                    <span className="text-xs text-muted-foreground shrink-0">
                      {Math.round(evidence.confidence * 100)}%
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
          {insight.supporting_evidence.length === 0 && (
            <p className="text-sm text-muted-foreground">No supporting evidence available</p>
          )}
        </div>
      </div>

      <Separator />

      {/* Risk Factors */}
      {insight.risk_factors.length > 0 && (
        <>
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-yellow-500" /> Risk Factors
            </h3>
            <ul className="space-y-2">
              {insight.risk_factors.map((risk, i) => (
                <li key={i} className="flex items-start gap-2 text-sm">
                  <span className="text-yellow-500 mt-1">-</span>
                  <span className="text-muted-foreground">{risk}</span>
                </li>
              ))}
            </ul>
          </div>
          <Separator />
        </>
      )}

      {/* Invalidation Trigger */}
      {insight.invalidation_trigger && (
        <>
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <Shield className="h-4 w-4 text-red-500" /> Invalidation Trigger
            </h3>
            <Card className="border-red-500/20 bg-red-500/5">
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">{insight.invalidation_trigger}</p>
              </CardContent>
            </Card>
          </div>
          <Separator />
        </>
      )}

      {/* Historical Precedent */}
      {insight.historical_precedent && (
        <>
          <div>
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <History className="h-4 w-4" /> Historical Precedent
            </h3>
            <Card className="bg-muted/30">
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">{insight.historical_precedent}</p>
              </CardContent>
            </Card>
          </div>
          <Separator />
        </>
      )}

      {/* Metadata */}
      <div className="flex flex-wrap gap-6 text-sm text-muted-foreground">
        {insight.analysts_involved.length > 0 && (
          <div>
            <span className="font-medium">Analysts:</span>{' '}
            {insight.analysts_involved.join(', ')}
          </div>
        )}
        {insight.data_sources.length > 0 && (
          <div className="flex items-center gap-1">
            <Database className="h-3 w-3" />
            <span className="font-medium">Sources:</span>{' '}
            {insight.data_sources.join(', ')}
          </div>
        )}
      </div>

      {/* Discovery Context - shows how this insight was discovered */}
      {insight.discovery_context && (
        <>
          <Separator />
          <DiscoveryContextCard
            context={insight.discovery_context}
            className="border-0 shadow-none p-0"
          />
        </>
      )}

      {/* Analysis Dimensions - collapsible section for TA, prediction markets, sentiment */}
      {(insight.technical_analysis_data || insight.prediction_market_data || insight.sentiment_data) && (
        <>
          <Separator />
          <AnalysisDimensionsSection insight={insight} />
        </>
      )}

      {/* Refresh Button */}
      <div className="pt-4">
        <Button variant="outline" onClick={onRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
          {isRefreshing ? 'Refreshing...' : 'Refresh Data'}
        </Button>
      </div>
    </div>
  );
}

// ============================================
// Conversations Panel
// ============================================

function ConversationsPanel({
  insightId,
  selectedConversationId,
  onSelectConversation,
  onCreateConversation,
  isCreating,
  onModificationApplied,
  onResearchLaunched,
}: {
  insightId: number;
  selectedConversationId: number | null;
  onSelectConversation: (id: number | null) => void;
  onCreateConversation: () => void;
  isCreating: boolean;
  onModificationApplied?: () => void;
  onResearchLaunched?: (researchId: number) => void;
}) {
  const { conversations, isLoading } = useInsightConversations(insightId);

  return (
    <div className="flex flex-col h-full">
      {/* Conversations Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <h3 className="font-medium">Conversations</h3>
        <Button
          size="sm"
          onClick={onCreateConversation}
          disabled={isCreating}
        >
          {isCreating ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Plus className="h-4 w-4 mr-1" />
          )}
          New
        </Button>
      </div>

      <Tabs
        value={selectedConversationId ? 'chat' : 'list'}
        onValueChange={(v) => {
          if (v === 'list') onSelectConversation(null);
        }}
        className="flex-1 flex flex-col"
      >
        <TabsList className="mx-4 mt-2" variant="line">
          <TabsTrigger value="list">
            <MessageSquare className="h-4 w-4 mr-1" />
            All ({conversations.length})
          </TabsTrigger>
          <TabsTrigger value="chat" disabled={!selectedConversationId}>
            Active Chat
          </TabsTrigger>
        </TabsList>

        {/* Conversations List */}
        <TabsContent value="list" className="flex-1 m-0">
          <ScrollArea className="h-full">
            <div className="p-4 space-y-2">
              {isLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-14 w-full" />
                  ))}
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <MessageSquare className="h-12 w-12 text-muted-foreground mb-4" />
                  <h4 className="text-lg font-medium mb-2">No Conversations Yet</h4>
                  <p className="text-sm text-muted-foreground max-w-xs mb-4">
                    Start a conversation to ask questions about this insight or request modifications.
                  </p>
                  <Button onClick={onCreateConversation} disabled={isCreating}>
                    {isCreating ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Plus className="h-4 w-4 mr-2" />
                    )}
                    Start Conversation
                  </Button>
                </div>
              ) : (
                conversations.map((conv) => (
                  <ConversationListItem
                    key={conv.id}
                    conversation={conv}
                    isActive={conv.id === selectedConversationId}
                    onClick={() => onSelectConversation(conv.id)}
                  />
                ))
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        {/* Active Conversation */}
        <TabsContent value="chat" className="flex-1 min-h-0 overflow-hidden m-0">
          {selectedConversationId && (
            <InsightConversationPanel
              conversationId={selectedConversationId}
              insightId={insightId}
              onModificationApplied={onModificationApplied}
              onResearchLaunched={onResearchLaunched}
            />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export function InsightDetailView({ insightId }: InsightDetailViewProps) {
  const router = useRouter();
  const queryClient = useQueryClient();

  // State
  const [selectedConversationId, setSelectedConversationId] = useState<number | null>(null);

  // Fetch insight data
  const { data: insight, isLoading, error, refetch, isFetching } = useDeepInsight(insightId);

  // Fetch portfolio for relevance badge
  const { data: portfolio } = usePortfolio();

  // Conversations
  const { createConversationAsync, isCreating } = useInsightConversations(insightId);

  // Handlers
  const handleRefresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  const handleSymbolClick = useCallback((symbol: string) => {
    router.push(`/stocks/${symbol}`);
  }, [router]);

  const handleCreateConversation = useCallback(async () => {
    try {
      const newConversation = await createConversationAsync({
        title: `Conversation ${new Date().toLocaleDateString()}`,
      });
      setSelectedConversationId(newConversation.id);
    } catch (err) {
      console.error('Failed to create conversation:', err);
    }
  }, [createConversationAsync]);

  const handleModificationApplied = useCallback(() => {
    // Refresh insight data when a modification is applied
    queryClient.invalidateQueries({ queryKey: deepInsightKeys.detail(insightId) });
  }, [queryClient, insightId]);

  const handleResearchLaunched = useCallback((researchId: number) => {
    console.log('Research launched:', researchId);
    // Could navigate to research page or show notification
  }, []);

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10" />
          <Skeleton className="h-8 w-64" />
        </div>
        <div className="grid lg:grid-cols-[1fr,400px] gap-6">
          <Card>
            <CardContent className="pt-6">
              <InsightDetailsSkeleton />
            </CardContent>
          </Card>
          <Card className="h-[600px]">
            <CardContent className="pt-6">
              <Skeleton className="h-full w-full" />
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !insight) {
    return (
      <div className="space-y-6">
        <Button variant="ghost" onClick={() => router.push('/insights')}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Insights
        </Button>
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <AlertTriangle className="h-12 w-12 text-destructive mb-4" />
            <CardTitle className="text-lg mb-2">Error Loading Insight</CardTitle>
            <CardDescription className="max-w-sm mb-4">
              {error instanceof Error ? error.message : 'Failed to load insight details'}
            </CardDescription>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => router.push('/insights')}>
                Back to Insights
              </Button>
              <Button onClick={() => refetch()}>
                Try Again
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Compute portfolio relevance
  const portfolioMatch = (() => {
    if (!portfolio?.holdings?.length) return null;
    const heldSymbols = new Set(portfolio.holdings.map((h) => h.symbol.toUpperCase()));
    const insightSymbols = [
      ...(insight.primary_symbol ? [insight.primary_symbol.toUpperCase()] : []),
      ...insight.related_symbols.map((s) => s.toUpperCase()),
    ];
    const matchedSymbols = insightSymbols.filter((s) => heldSymbols.has(s));
    if (matchedSymbols.length === 0) return null;
    // Sum allocation_pct for matched holdings
    const totalAllocation = portfolio.holdings
      .filter((h) => matchedSymbols.includes(h.symbol.toUpperCase()))
      .reduce((sum, h) => sum + (h.allocation_pct ?? 0), 0);
    return {
      symbols: matchedSymbols,
      allocationPct: totalAllocation > 0 ? totalAllocation : undefined,
    };
  })();

  return (
    <div className="space-y-6">
      {/* Back Navigation */}
      <Button variant="ghost" onClick={() => router.push('/insights')}>
        <ArrowLeft className="h-4 w-4 mr-2" />
        Back to Insights
      </Button>

      {/* Two-Column Layout */}
      <div className="grid lg:grid-cols-[1fr,400px] gap-6">
        {/* Left Column: Insight Details */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Target className="h-5 w-5" />
              Insight Details
            </CardTitle>
            <CardDescription>
              Deep analysis synthesized from multiple AI analysts
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[calc(100vh-280px)] pr-4">
              <InsightDetailsPanel
                insight={insight}
                onRefresh={handleRefresh}
                isRefreshing={isFetching}
                onSymbolClick={handleSymbolClick}
                portfolioMatch={portfolioMatch}
              />
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Right Column: Conversations */}
        <Card className="h-[calc(100vh-200px)] flex flex-col">
          <ConversationsPanel
            insightId={insightId}
            selectedConversationId={selectedConversationId}
            onSelectConversation={setSelectedConversationId}
            onCreateConversation={handleCreateConversation}
            isCreating={isCreating}
            onModificationApplied={handleModificationApplied}
            onResearchLaunched={handleResearchLaunched}
          />
        </Card>
      </div>
    </div>
  );
}
