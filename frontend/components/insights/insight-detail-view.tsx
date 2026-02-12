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
import { TooltipProvider } from '@/components/ui/tooltip';
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

function getRatingBadgeClass(rating: string): string {
  return TA_RATING_STYLES[rating.toLowerCase()] ?? 'bg-gray-500 text-white';
}

function getMoodBadgeClass(mood: string): string {
  const lower = mood.toLowerCase();
  if (lower.includes('bullish')) return 'bg-green-600 text-white';
  if (lower.includes('bearish')) return 'bg-red-600 text-white';
  return 'bg-gray-500 text-white';
}

/** Renders a horizontal bar for a value in [-1, +1] range */
function SignalBar({ label, value }: { label: string; value: number }) {
  // Normalize: -1 maps to 0%, 0 maps to 50%, +1 maps to 100%
  const pct = Math.round((value + 1) * 50);
  const isPositive = value >= 0;

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted-foreground w-20 shrink-0 capitalize">{label}</span>
      <div className="flex-1 h-2 rounded-full bg-muted relative overflow-hidden">
        {/* Center line */}
        <div className="absolute left-1/2 top-0 h-full w-px bg-muted-foreground/30" />
        {/* Value bar: grows from center */}
        <div
          className={cn(
            'absolute top-0 h-full rounded-full transition-all',
            isPositive ? 'bg-green-500' : 'bg-red-500'
          )}
          style={
            isPositive
              ? { left: '50%', width: `${value * 50}%` }
              : { left: `${50 + value * 50}%`, width: `${Math.abs(value) * 50}%` }
          }
        />
      </div>
      <span className={cn('text-xs font-mono w-10 text-right', isPositive ? 'text-green-500' : 'text-red-500')}>
        {value > 0 ? '+' : ''}{value.toFixed(2)}
      </span>
    </div>
  );
}

// ============================================
// Analysis Dimensions Section
// ============================================

function AnalysisDimensionsSection({ insight }: { insight: DeepInsight }) {
  const ta = insight.technical_analysis_data;
  const pred = insight.prediction_market_data;
  const sent = insight.sentiment_data;

  return (
    <Collapsible>
      <CollapsibleTrigger className="flex items-center gap-2 w-full py-2 group">
        <BarChart3 className="h-4 w-4" />
        <span className="text-sm font-semibold">Analysis Dimensions</span>
        <ChevronDown className="h-4 w-4 ml-auto transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="space-y-5 pt-3">
        {/* Technical Analysis */}
        {ta && (
          <div className="space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" />
              Technical Analysis
            </h4>
            <div className="rounded-lg border border-border/50 bg-muted/20 p-4 space-y-4">
              {/* Rating and confidence row */}
              <div className="flex items-center gap-3 flex-wrap">
                <Badge className={cn('text-xs px-3 py-1', getRatingBadgeClass(ta.rating))}>
                  {ta.rating}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  Score: <span className="font-mono font-medium text-foreground">{ta.composite_score.toFixed(2)}</span>
                </span>
                <span className="text-sm text-muted-foreground">
                  Confidence: <span className="font-mono font-medium text-foreground">{Math.round(ta.confidence * 100)}%</span>
                </span>
              </div>

              {/* Breakdown bars */}
              {ta.breakdown && (
                <div className="space-y-2">
                  <SignalBar label="Trend" value={ta.breakdown.trend} />
                  <SignalBar label="Momentum" value={ta.breakdown.momentum} />
                  <SignalBar label="Volatility" value={ta.breakdown.volatility} />
                  <SignalBar label="Volume" value={ta.breakdown.volume} />
                </div>
              )}

              {/* Support / Resistance levels */}
              {ta.key_levels && (
                <div className="flex flex-wrap gap-4 text-xs">
                  {ta.key_levels.support.length > 0 && (
                    <div>
                      <span className="text-muted-foreground">Support: </span>
                      <span className="font-mono text-green-500">
                        {ta.key_levels.support.map((l) => l.toLocaleString()).join(', ')}
                      </span>
                    </div>
                  )}
                  {ta.key_levels.resistance.length > 0 && (
                    <div>
                      <span className="text-muted-foreground">Resistance: </span>
                      <span className="font-mono text-red-500">
                        {ta.key_levels.resistance.map((l) => l.toLocaleString()).join(', ')}
                      </span>
                    </div>
                  )}
                  {ta.key_levels.pivot != null && (
                    <div>
                      <span className="text-muted-foreground">Pivot: </span>
                      <span className="font-mono text-foreground">{ta.key_levels.pivot.toLocaleString()}</span>
                    </div>
                  )}
                </div>
              )}

              {/* Signals */}
              {ta.signals && ta.signals.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {ta.signals.map((sig, i) => (
                    <Badge key={i} variant="outline" className="text-xs">
                      {sig}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Prediction Markets */}
        {pred && (
          <div className="space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <Globe className="h-3.5 w-3.5" />
              Prediction Markets
            </h4>
            <div className="rounded-lg border border-border/50 bg-muted/20 p-4 space-y-3">
              {/* Fed rate probabilities */}
              {pred.fed_rates?.next_meeting?.probabilities && (
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-medium text-foreground">Fed Rate Probabilities</span>
                    {pred.fed_rates.next_meeting.date && (
                      <span className="text-xs text-muted-foreground">({pred.fed_rates.next_meeting.date})</span>
                    )}
                    {pred.fed_rates.source && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">{pred.fed_rates.source}</Badge>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(pred.fed_rates.next_meeting.probabilities).map(([action, prob]) => (
                      <div key={action} className="flex items-center gap-1.5 text-xs">
                        <span className="text-muted-foreground capitalize">{action}:</span>
                        <span className="font-mono font-medium text-foreground">{typeof prob === 'number' ? `${Math.round(prob * 100)}%` : String(prob)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recession probability */}
              {pred.recession?.probability_2026 != null && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Recession Probability (2026):</span>
                  <span className="font-mono font-medium text-foreground">{Math.round(pred.recession.probability_2026 * 100)}%</span>
                  {pred.recession.source && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">{pred.recession.source}</Badge>
                  )}
                </div>
              )}

              {/* Inflation */}
              {pred.inflation?.cpi_above_3pct != null && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">CPI &gt; 3% Probability:</span>
                  <span className="font-mono font-medium text-foreground">{Math.round(pred.inflation.cpi_above_3pct * 100)}%</span>
                  {pred.inflation.source && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">{pred.inflation.source}</Badge>
                  )}
                </div>
              )}

              {/* GDP */}
              {pred.gdp?.q1_positive != null && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Q1 GDP Positive:</span>
                  <span className="font-mono font-medium text-foreground">{Math.round(pred.gdp.q1_positive * 100)}%</span>
                  {pred.gdp.source && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0">{pred.gdp.source}</Badge>
                  )}
                </div>
              )}

              {/* S&P 500 targets */}
              {pred.sp500?.targets && pred.sp500.targets.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-medium text-foreground">S&P 500 Targets</span>
                    {pred.sp500.source && (
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0">{pred.sp500.source}</Badge>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {pred.sp500.targets.map((t, i) => (
                      <div key={i} className="flex items-center gap-1 text-xs rounded-md border border-border/50 bg-background px-2 py-1">
                        <span className="font-mono font-medium">{t.level.toLocaleString()}</span>
                        <span className="text-muted-foreground">({Math.round(t.probability * 100)}%)</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Reddit / Social Sentiment */}
        {sent && (
          <div className="space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
              <MessageCircle className="h-3.5 w-3.5" />
              Social Sentiment
            </h4>
            <div className="rounded-lg border border-border/50 bg-muted/20 p-4 space-y-3">
              {/* Overall mood */}
              {sent.overall_mood && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Overall Mood:</span>
                  <Badge className={cn('text-xs px-2 py-0.5', getMoodBadgeClass(sent.overall_mood))}>
                    {sent.overall_mood}
                  </Badge>
                </div>
              )}

              {/* Trending tickers */}
              {sent.trending && sent.trending.length > 0 && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-1.5">Trending Tickers</span>
                  <div className="flex flex-wrap gap-2">
                    {sent.trending.map((item, i) => (
                      <div key={i} className="flex items-center gap-1.5 text-xs rounded-md border border-border/50 bg-background px-2 py-1">
                        <span className="font-mono font-medium">{item.ticker}</span>
                        <span className="text-muted-foreground">{item.mentions} mentions</span>
                        {item.upvotes != null && (
                          <span className="text-muted-foreground">/ {item.upvotes} upvotes</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Per-symbol sentiment */}
              {sent.per_symbol && sent.per_symbol.length > 0 && (
                <div>
                  <span className="text-xs text-muted-foreground block mb-1.5">Per-Symbol Sentiment</span>
                  <div className="space-y-1.5">
                    {sent.per_symbol.map((sym, i) => {
                      const scoreColor = sym.sentiment_score >= 0.3
                        ? 'text-green-500'
                        : sym.sentiment_score <= -0.3
                          ? 'text-red-500'
                          : 'text-gray-400';
                      return (
                        <div key={i} className="flex items-center gap-3 text-xs">
                          <span className="font-mono font-medium w-16">{sym.symbol}</span>
                          <span className={cn('font-mono w-12 text-right', scoreColor)}>
                            {sym.sentiment_score > 0 ? '+' : ''}{sym.sentiment_score.toFixed(2)}
                          </span>
                          <span className="text-muted-foreground">{sym.post_count} posts</span>
                          {sym.bullish_count != null && sym.bearish_count != null && (
                            <span className="text-muted-foreground">
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
