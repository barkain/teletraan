'use client';

import { useState, useCallback, useMemo } from 'react';
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
  Globe,
  MessageCircle,
  GitBranch,
  PieChart,
  Layers,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { Progress } from '@/components/ui/progress';
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
import type { DeepInsight, InsightAction, AnalystEvidence } from '@/types';

// ============================================
// Types
// ============================================

interface InsightDetailViewProps {
  insightId: number;
}

// ============================================
// Design System Constants
// ============================================

type AnalysisDimensionType = 'technical' | 'macro' | 'sector' | 'risk' | 'correlation' | 'sentiment' | 'prediction';

interface DimensionConfig {
  label: string;
  icon: typeof TrendingUp;
  color: string;       // text color class
  borderColor: string;  // left border color class
  bgColor: string;      // light background tint
  badgeBg: string;      // badge background
}

const DIMENSION_CONFIG: Record<AnalysisDimensionType, DimensionConfig> = {
  technical: {
    label: 'Technical Analysis',
    icon: TrendingUp,
    color: 'text-blue-500 dark:text-blue-400',
    borderColor: 'border-l-blue-500',
    bgColor: 'bg-blue-500/5',
    badgeBg: 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
  },
  macro: {
    label: 'Macro Analysis',
    icon: Globe,
    color: 'text-purple-500 dark:text-purple-400',
    borderColor: 'border-l-purple-500',
    bgColor: 'bg-purple-500/5',
    badgeBg: 'bg-purple-500/10 text-purple-600 dark:text-purple-400',
  },
  sector: {
    label: 'Sector Analysis',
    icon: PieChart,
    color: 'text-emerald-500 dark:text-emerald-400',
    borderColor: 'border-l-emerald-500',
    bgColor: 'bg-emerald-500/5',
    badgeBg: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  },
  risk: {
    label: 'Risk Assessment',
    icon: Shield,
    color: 'text-rose-500 dark:text-rose-400',
    borderColor: 'border-l-rose-500',
    bgColor: 'bg-rose-500/5',
    badgeBg: 'bg-rose-500/10 text-rose-600 dark:text-rose-400',
  },
  correlation: {
    label: 'Correlation Analysis',
    icon: GitBranch,
    color: 'text-amber-500 dark:text-amber-400',
    borderColor: 'border-l-amber-500',
    bgColor: 'bg-amber-500/5',
    badgeBg: 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  },
  sentiment: {
    label: 'Social Sentiment',
    icon: MessageCircle,
    color: 'text-cyan-500 dark:text-cyan-400',
    borderColor: 'border-l-cyan-500',
    bgColor: 'bg-cyan-500/5',
    badgeBg: 'bg-cyan-500/10 text-cyan-600 dark:text-cyan-400',
  },
  prediction: {
    label: 'Prediction Markets',
    icon: BarChart3,
    color: 'text-violet-500 dark:text-violet-400',
    borderColor: 'border-l-violet-500',
    bgColor: 'bg-violet-500/5',
    badgeBg: 'bg-violet-500/10 text-violet-600 dark:text-violet-400',
  },
};

// ============================================
// Action Config
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
// Layman Language Helper
// ============================================

/**
 * Generate a complete plain-English rewrite of technical market text.
 *
 * Instead of inserting parenthetical definitions inline, this function detects
 * the overall meaning of the sentence and produces a fully rewritten explanation
 * in conversational English. Returns null when no meaningful simplification is possible.
 */
function laymanExplain(text: string, _analystHint?: string): string | null {
  if (!text || text.trim().length === 0) return null;

  // --- Tier 1: Full-sentence pattern rewrites ---

  // VaR with range
  const varRange = text.match(/VaR\s*([\d.]+)[-–]([\d.]+)%/i);
  if (varRange) {
    const hasConcentration = /concentrat|cluster|correlat/i.test(text);
    let result = `On a bad day, your portfolio could drop ${varRange[1]}-${varRange[2]}%.`;
    if (hasConcentration) {
      result += ' This is higher than normal because your investments are bunched together in similar stocks.';
    }
    return result;
  }

  // VaR single
  const varSingle = text.match(/VaR\s*([\d.]+)%/i);
  if (varSingle) {
    return `On a bad day, your portfolio could drop about ${varSingle[1]}%. This kind of loss happens roughly 1 in 20 trading days.`;
  }

  // Late/mid/early cycle with recession + stagflation
  const cycleFullMatch = text.match(/(late|mid|early)[- ]cycle.*?(\d+)%\s*(?:confidence|prob).*?(\d+)%\s*recession.*?(\d+)%\s*stagflation/i);
  if (cycleFullMatch) {
    const phaseLookup: Record<string, string> = { late: 'running out of steam', mid: 'in the middle of its growth phase', early: 'in the early stages of recovery' };
    const phasePhrase = phaseLookup[cycleFullMatch[1].toLowerCase()] || 'at a turning point';
    const rec = parseInt(cycleFullMatch[3]);
    const stag = parseInt(cycleFullMatch[4]);
    const recDesc = rec === 50 ? 'a coin-flip chance' : `about a ${rec}% chance`;
    return `The economy looks like it's ${phasePhrase}. There's ${recDesc} we enter a recession, and about 1-in-${Math.round(100 / stag)} odds of stagflation (prices rising while the economy stalls). Both scenarios would hit growth-oriented investments hardest.`;
  }

  // Late/mid/early cycle with recession
  const cycleRecMatch = text.match(/(late|mid|early)[- ]cycle.*?(\d+)%\s*recession/i);
  if (cycleRecMatch) {
    const phaseLookup: Record<string, string> = { late: 'running out of steam', mid: 'in the middle of its growth phase', early: 'in the early stages of recovery' };
    const phasePhrase = phaseLookup[cycleRecMatch[1].toLowerCase()] || 'at a turning point';
    const rec = parseInt(cycleRecMatch[2]);
    const recDesc = rec === 50 ? 'a coin-flip chance' : rec > 60 ? `a high ${rec}% chance` : `about a ${rec}% chance`;
    return `The economy looks like it's ${phasePhrase}, with ${recDesc} of a recession.`;
  }

  // Squeeze + parabolic = synchronized risk
  const syncRisk = text.match(/squeeze.*?\(([^)]+)\).*?parabolic.*?\(([^)]+)\)/i);
  if (syncRisk) {
    return `${syncRisk[1].trim()} are coiling up for a big move -- like a compressed spring. Meanwhile, ${syncRisk[2].trim()} have been rising at an unsustainable pace. The risk is these all unwind at the same time.`;
  }

  // Distribution signals with symbols
  const distSig = text.match(/distribution\s+signals?\s*\(([^)]+)\)/i);
  if (distSig) {
    return `It looks like big investors may be quietly selling ${distSig[1].trim()} while prices are still high.`;
  }

  // RSI divergence + MACD crossover + support
  const rsiMacdSupport = text.match(/RSI\s+divergence.*MACD\s+(?:bearish\s+)?crossover.*support\s+(?:at\s+)?\$?([\d,.]+)/i);
  if (rsiMacdSupport) {
    return `The stock's momentum is fading even as the price holds steady -- a warning sign. The trend indicators just flipped negative, and the price is at a critical floor of $${rsiMacdSupport[1]}. If it drops below, expect a bigger decline.`;
  }

  // RSI divergence + MACD
  if (/RSI\s+divergence.*MACD/i.test(text)) {
    return 'The stock\'s momentum is fading while the price holds steady -- a warning sign. The trend indicators are confirming that the current move may be losing steam.';
  }

  // RSI with value
  const rsiVal = text.match(/RSI\s*(?:at|above|below|near|of|is)?\s*(\d+)/i);
  if (rsiVal) {
    const val = parseInt(rsiVal[1]);
    if (val >= 70) return `The stock's momentum gauge reads ${val}/100 -- it's been running hot and may be due for a pullback.`;
    if (val <= 30) return `The stock's momentum gauge reads just ${val}/100 -- it's been beaten down and may be due for a bounce.`;
    return `The stock's momentum is in a neutral zone at ${val}/100, with no strong push in either direction.`;
  }

  // MACD bearish
  if (/MACD\s+bearish/i.test(text)) return 'A key trend indicator just flipped negative -- the upward momentum is fading and caution is warranted.';
  // MACD bullish
  if (/MACD\s+(?:bullish|cross)/i.test(text)) return 'A key trend indicator just flipped positive, suggesting the downward pressure is easing.';
  // MACD divergence
  if (/MACD\s+divergence/i.test(text)) return 'Price and a key trend indicator are telling different stories -- this often signals a reversal is coming.';

  // Support level
  const support = text.match(/support\s+(?:at|near|around|level|of)?\s*\$?([\d,.]+)/i);
  if (support) return `There's a price floor around $${support[1]} where buyers have historically stepped in. If it breaks, expect a sharper drop.`;

  // Resistance level
  const resistance = text.match(/resistance\s+(?:at|near|around|level|of)?\s*\$?([\d,.]+)/i);
  if (resistance) return `There's a price ceiling around $${resistance[1]} where sellers have historically cashed out. Breaking through would be bullish.`;

  // Breakout
  if (/break(?:out|ing\s+out)\s+(?:above|from|through)/i.test(text)) return 'The price just broke through a key ceiling, which often attracts new buyers and leads to further gains.';

  // Breakdown
  if (/break(?:down|ing\s+down)\s+(?:below|from|through)/i.test(text)) return 'The price just fell through a key floor, which often triggers more selling.';

  // Squeeze
  const squeezeMatch = text.match(/squeeze\s*\(([^)]+)\)/i);
  if (squeezeMatch) return `${squeezeMatch[1].trim()} are coiling up for a big move -- like a compressed spring that could snap either way.`;
  if (/squeeze/i.test(text)) return 'Price swings have gotten unusually small -- like the calm before a storm. A big move is likely coming soon.';

  // Accumulation
  if (/accumulation/i.test(text)) return 'Large investors appear to be quietly buying, building positions while the price is still low.';
  // Distribution
  if (/distribution/i.test(text)) return 'Large investors appear to be quietly selling while prices are still high.';

  // Parabolic
  if (/parabolic/i.test(text)) return 'The price has been rising at an unsustainable pace. Like a ball thrown in the air, it will eventually come back down.';

  // Stagflation
  if (/stagflation/i.test(text)) return 'There\'s a risk of stagflation -- prices keep rising while the economy stalls. It\'s tough for most investments.';

  // Late-cycle alone
  if (/late[- ]cycle/i.test(text)) return 'The economy appears to be in the later stages of its growth cycle. Historically, this is when markets become more volatile.';

  // Breadth narrowing
  if (/breadth\s+(?:narrowing|declining|weakening)/i.test(text)) return 'Fewer stocks are participating in the rally, which is a warning sign for the broader market.';
  // Breadth improving
  if (/breadth\s+(?:improving|expanding|strengthening)/i.test(text)) return 'More stocks are joining the rally -- a healthy sign that the uptrend has staying power.';

  // Volatility
  if (/volatility\s+(?:expansion|spike|surge)/i.test(text)) return 'Market swings are getting bigger -- expect larger daily price moves in both directions.';
  if (/volatility\s+(?:contraction|compression|low)/i.test(text)) return 'The market has been unusually calm. This quiet often comes before a sharp move.';

  // Momentum fading
  if (/momentum\s+(?:divergence|weakening|fading|stalling)/i.test(text)) return 'The speed of price moves is slowing down -- the stock is coasting and may be losing direction.';

  // Yield curve
  if (/(?:yield\s+curve\s+)?invert(?:ed|ion)/i.test(text)) return 'Short-term bonds are paying more than long-term ones (unusual) -- historically one of the most reliable recession warning signs.';
  if (/yield\s+curve\s+steepening/i.test(text)) return 'The gap between short and long-term rates is widening, which typically signals expectations of stronger economic growth.';

  // Recession probability
  const recProb = text.match(/(\d+)%\s*(?:recession|chance of recession)/i);
  if (recProb) {
    const pct = parseInt(recProb[1]);
    if (pct >= 70) return `There's a ${pct}% chance of a recession -- the economy may shrink, which would be bad for most investments.`;
    if (pct >= 40) return `There's a meaningful ${pct}% chance of recession -- not certain, but high enough to warrant caution.`;
    return `Recession risk is relatively low at ${pct}%.`;
  }

  // Mean reversion
  if (/mean\s+reversion/i.test(text)) return 'Prices have stretched far from their average and may snap back, like a rubber band being pulled.';

  // Head and shoulders
  if (/head\s+and\s+shoulders/i.test(text)) return 'The price chart has formed a pattern that often appears before a significant downturn.';
  // Golden cross
  if (/golden\s+cross/i.test(text)) return 'A rare bullish signal: the short-term trend crossed above the long-term trend, suggesting upward momentum.';
  // Death cross
  if (/death\s+cross/i.test(text)) return 'A bearish signal: the short-term trend crossed below the long-term trend, suggesting downward momentum.';
  // Double top
  if (/double\s+top/i.test(text)) return 'The price tried to break higher twice and failed both times -- this often signals the stock has hit its ceiling.';
  // Double bottom
  if (/double\s+bottom/i.test(text)) return 'The price bounced off the same floor twice -- this often signals the worst is over.';
  // Regime shift
  if (/regime\s+(?:change|shift|transition)/i.test(text)) return 'The overall market environment is fundamentally changing. Strategies that worked recently may stop working.';

  // Overbought
  if (/overbought/i.test(text)) return 'The stock has risen fast and may be stretched too high -- it could be due for a pullback.';
  // Oversold
  if (/oversold/i.test(text)) return 'The stock has fallen fast and may have been pushed too low -- it could be due for a bounce.';

  // Bollinger
  if (/bollinger/i.test(text)) return 'The price is near the edge of its normal trading range, which often signals an upcoming move.';

  // SMA/EMA
  if (/\b(?:SMA|EMA)\b/i.test(text) && /cross/i.test(text)) return 'The short-term and long-term price averages just crossed, which is a signal that the trend may be shifting.';

  // --- Tier 2: No specific pattern matched, return null to signal "no simplification" ---
  return null;
}

/** Map analyst names from supporting evidence to dimension types. */
function analystToDimension(analyst: string): AnalysisDimensionType | null {
  const lower = analyst.toLowerCase();
  if (lower.includes('technical') || lower.includes('ta')) return 'technical';
  if (lower.includes('macro')) return 'macro';
  if (lower.includes('sector')) return 'sector';
  if (lower.includes('risk')) return 'risk';
  if (lower.includes('correlation')) return 'correlation';
  if (lower.includes('sentiment')) return 'sentiment';
  if (lower.includes('prediction')) return 'prediction';
  return null;
}

// ============================================
// Helper Functions
// ============================================

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

function ConfidenceGauge({ confidence, size = 'md' }: { confidence: number; size?: 'sm' | 'md' | 'lg' }) {
  const percentage = Math.round(confidence * 100);
  const getColor = () => {
    if (percentage >= 80) return 'text-green-600 dark:text-green-400';
    if (percentage >= 60) return 'text-yellow-600 dark:text-yellow-400';
    return 'text-red-600 dark:text-red-400';
  };
  const getProgressColor = () => {
    if (percentage >= 80) return '[&>[data-slot=progress-indicator]]:bg-green-500';
    if (percentage >= 60) return '[&>[data-slot=progress-indicator]]:bg-yellow-500';
    return '[&>[data-slot=progress-indicator]]:bg-red-500';
  };

  if (size === 'sm') {
    return (
      <div className="flex items-center gap-2">
        <Progress value={percentage} className={cn('h-1.5 w-16', getProgressColor())} />
        <span className={cn('text-xs font-semibold', getColor())}>{percentage}%</span>
      </div>
    );
  }

  return (
    <div className="rounded-lg px-4 py-3 text-center bg-card/80 backdrop-blur-sm border border-border/50">
      <div className={cn('text-3xl font-bold', getColor())}>{percentage}%</div>
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Confidence</div>
      <Progress value={percentage} className={cn('h-1.5 mt-2', getProgressColor())} />
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
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    </div>
  );
}

// ============================================
// Dimension Section Wrapper
// ============================================

/** Glassmorphism card wrapper for each analysis dimension section. */
function DimensionSectionCard({
  dimension,
  defaultOpen = false,
  alwaysOpen = false,
  children,
  confidence,
}: {
  dimension: AnalysisDimensionType;
  defaultOpen?: boolean;
  alwaysOpen?: boolean;
  children: React.ReactNode;
  confidence?: number;
}) {
  const config = DIMENSION_CONFIG[dimension];
  const Icon = config.icon;

  if (alwaysOpen) {
    return (
      <div
        className={cn(
          'rounded-xl border-l-4 bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden',
          config.borderColor
        )}
      >
        <div className={cn('flex items-center gap-3 px-5 py-4 border-b border-border/30', config.bgColor)}>
          <div className={cn('p-1.5 rounded-md', config.badgeBg)}>
            <Icon className={cn('h-4 w-4', config.color)} />
          </div>
          <span className="text-sm font-semibold text-foreground">{config.label}</span>
          {confidence != null && (
            <div className="ml-auto">
              <ConfidenceGauge confidence={confidence} size="sm" />
            </div>
          )}
        </div>
        <div className="p-5">{children}</div>
      </div>
    );
  }

  return (
    <Collapsible defaultOpen={defaultOpen}>
      <div
        className={cn(
          'rounded-xl border-l-4 bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden',
          config.borderColor
        )}
      >
        <CollapsibleTrigger className="flex items-center gap-3 w-full px-5 py-4 border-b border-border/30 group hover:bg-muted/30 transition-colors">
          <div className={cn('p-1.5 rounded-md', config.badgeBg)}>
            <Icon className={cn('h-4 w-4', config.color)} />
          </div>
          <span className="text-sm font-semibold text-foreground">{config.label}</span>
          {confidence != null && (
            <div className="ml-auto mr-3">
              <ConfidenceGauge confidence={confidence} size="sm" />
            </div>
          )}
          <ChevronDown className="h-4 w-4 text-muted-foreground ml-auto transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="p-5">{children}</div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}

/** Evidence items belonging to a specific dimension, with layman explanations. */
function DimensionEvidence({ evidence }: { evidence: AnalystEvidence[] }) {
  if (evidence.length === 0) return null;
  return (
    <div className="space-y-2 mt-3 pt-3 border-t border-border/30">
      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Analyst Findings</span>
      {evidence.map((ev, i) => (
        <div key={i} className="flex items-start gap-2">
          <span className="text-muted-foreground mt-0.5 shrink-0">--</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-foreground">{ev.finding}</p>
            <p className="text-xs text-muted-foreground italic mt-0.5 leading-relaxed">
              {laymanExplain(ev.finding) ?? 'No additional explanation needed.'}
            </p>
          </div>
          {ev.confidence != null && (
            <span className="text-xs text-muted-foreground shrink-0">
              {Math.round(ev.confidence * 100)}%
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ============================================
// Technical Analysis Helpers (preserved from original)
// ============================================

const TA_RATING_STYLES: Record<string, string> = {
  'strong buy': 'bg-green-600 text-white',
  'buy': 'bg-green-500 text-white',
  'neutral': 'bg-gray-500 text-white',
  'sell': 'bg-orange-500 text-white',
  'strong sell': 'bg-red-600 text-white',
};

function buildTARatingExplanation(ta: NonNullable<DeepInsight['technical_analysis_data']>): string {
  const parts: string[] = [];
  const score = ta.composite_score;
  const bd = ta.breakdown;

  if (score != null) {
    const scoreAbs = Math.abs(score);
    const direction = score >= 0 ? 'bullish' : 'bearish';
    const strength = scoreAbs > 0.6 ? 'strongly' : scoreAbs > 0.3 ? 'moderately' : 'mildly';
    parts.push(`Composite score ${score >= 0 ? '+' : ''}${score.toFixed(2)} -- ${strength} ${direction}`);
  }

  if (bd) {
    const drivers: string[] = [];
    if (Math.abs(bd.trend) > 0.3) drivers.push(`trend at ${bd.trend >= 0 ? '+' : ''}${bd.trend.toFixed(2)}`);
    if (Math.abs(bd.momentum) > 0.3) drivers.push(`momentum at ${bd.momentum >= 0 ? '+' : ''}${bd.momentum.toFixed(2)}`);
    if (Math.abs(bd.volume) > 0.3) drivers.push(`volume at ${bd.volume >= 0 ? '+' : ''}${bd.volume.toFixed(2)}`);
    if (drivers.length > 0) parts.push(`Driven by ${drivers.join(', ')}`);

    const divergences: string[] = [];
    if (bd.trend > 0.2 && bd.momentum < -0.2) divergences.push('Trend is positive but momentum is fading -- potential reversal risk');
    else if (bd.trend < -0.2 && bd.momentum > 0.2) divergences.push('Momentum is building despite weak trend -- watch for breakout');
    if (bd.momentum > 0.3 && bd.volume < -0.2) divergences.push('Momentum rising on declining volume -- move may lack conviction');
    if (bd.volatility > 0.5) divergences.push(`Volatility elevated at ${bd.volatility >= 0 ? '+' : ''}${bd.volatility.toFixed(2)} -- expect outsized moves`);
    if (divergences.length > 0) parts.push(divergences.join('. '));
  }

  return parts.length > 0 ? parts.join('. ') + '.' : 'Technical indicators have been evaluated.';
}

function buildTALaymanSummary(ta: NonNullable<DeepInsight['technical_analysis_data']>): string {
  const rating = ta.rating.toLowerCase();
  const ratingText = rating.includes('buy') ? 'The charts suggest this may be a good entry point.'
    : rating.includes('sell') ? 'The charts suggest caution -- the price may be stretched.'
    : 'The charts show a mixed picture with no clear direction.';

  const parts = [ratingText];
  if (ta.key_levels) {
    if (ta.key_levels.support.length > 0) {
      const nearest = Math.max(...ta.key_levels.support);
      parts.push(`Key price floor to watch: $${nearest.toLocaleString()}.`);
    }
    if (ta.key_levels.resistance.length > 0) {
      const nearest = Math.min(...ta.key_levels.resistance);
      parts.push(`Key price ceiling to watch: $${nearest.toLocaleString()}.`);
    }
  }
  return parts.join(' ');
}

function buildKeyLevelsExplanation(ta: NonNullable<DeepInsight['technical_analysis_data']>): string | null {
  const kl = ta.key_levels;
  if (!kl) return null;
  const parts: string[] = [];
  if (kl.support.length > 0) {
    const nearest = Math.max(...kl.support);
    parts.push(`Nearest support at $${nearest.toLocaleString()} -- a break below could accelerate selling`);
  }
  if (kl.resistance.length > 0) {
    const nearest = Math.min(...kl.resistance);
    parts.push(`Nearest resistance at $${nearest.toLocaleString()} -- needs a break above for continuation`);
  }
  if (kl.pivot != null && kl.support.length > 0 && kl.resistance.length > 0) {
    const range = Math.min(...kl.resistance) - Math.max(...kl.support);
    if (range > 0) parts.push(`Trading range: $${range.toLocaleString()} between key support and resistance`);
  }
  return parts.length > 0 ? parts.join('. ') + '.' : null;
}

function describeBreakdownValue(
  dimension: 'trend' | 'momentum' | 'volatility' | 'volume',
  value: number,
): { label: string; arrow: string; color: string; explanation: string } {
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

function normalizeForRadar(value: number): number {
  return Math.max(0, Math.min(1, (value + 1) / 2));
}

// ============================================
// Sentiment Helpers
// ============================================

function buildSentimentLaymanSummary(sent: NonNullable<DeepInsight['sentiment_data']>, ta: DeepInsight['technical_analysis_data']): string {
  const mood = (sent.overall_mood ?? '').toLowerCase();
  let moodText: string;
  if (mood.includes('very bullish')) moodText = 'Market mood is very optimistic.';
  else if (mood.includes('bullish')) moodText = 'Market mood is optimistic.';
  else if (mood.includes('very bearish')) moodText = 'Market mood is very pessimistic.';
  else if (mood.includes('bearish')) moodText = 'Market mood is pessimistic.';
  else moodText = 'Market mood is mixed with no clear direction.';

  const parts = [moodText];

  if (sent.per_symbol && sent.per_symbol.length > 0) {
    const totalPosts = sent.per_symbol.reduce((sum, s) => sum + s.post_count, 0);
    parts.push(`Based on ${totalPosts} social media posts analyzed.`);
  }

  if (ta?.breakdown) {
    const trendSignal = ta.breakdown.trend;
    if (mood.includes('bullish') && trendSignal < -0.2) {
      parts.push('Note: Social sentiment disagrees with technical signals (contrarian warning).');
    } else if (mood.includes('bearish') && trendSignal > 0.2) {
      parts.push('Note: Social sentiment is more negative than technicals suggest (possible contrarian opportunity).');
    }
  }

  return parts.join(' ');
}

function buildSentimentExplanation(
  sent: NonNullable<DeepInsight['sentiment_data']>,
  ta: DeepInsight['technical_analysis_data'],
): string {
  const parts: string[] = [];
  const mood = sent.overall_mood ?? '';
  const lower = mood.toLowerCase();

  if (sent.per_symbol && sent.per_symbol.length > 0) {
    const totalPosts = sent.per_symbol.reduce((sum, s) => sum + s.post_count, 0);
    const bullishSymbols = sent.per_symbol.filter((s) => s.sentiment_score > 0.2);
    const bearishSymbols = sent.per_symbol.filter((s) => s.sentiment_score < -0.2);
    parts.push(`${totalPosts} posts analyzed across ${sent.per_symbol.length} symbols`);
    if (bullishSymbols.length > 0) parts.push(`Bullish on: ${bullishSymbols.map((s) => s.symbol).join(', ')}`);
    if (bearishSymbols.length > 0) parts.push(`Bearish on: ${bearishSymbols.map((s) => s.symbol).join(', ')}`);
  } else if (lower.includes('bullish')) {
    parts.push('Social sentiment skews bullish across monitored subreddits');
  } else if (lower.includes('bearish')) {
    parts.push('Social sentiment skews bearish across monitored subreddits');
  } else {
    parts.push('Mixed opinions across trading communities -- no strong directional bias');
  }

  if (sent.trending && sent.trending.length > 0) {
    const totalMentions = sent.trending.reduce((sum, t) => sum + t.mentions, 0);
    parts.push(`${totalMentions} total mentions across ${sent.trending.length} trending tickers`);
  }

  if (ta?.breakdown) {
    const trendSignal = ta.breakdown.trend;
    if (lower.includes('bullish') && trendSignal < -0.2) {
      parts.push('Note: Reddit sentiment is bullish but technical trend is negative -- retail traders may be lagging a deteriorating setup');
    } else if (lower.includes('bearish') && trendSignal > 0.2) {
      parts.push('Note: Reddit sentiment is bearish despite positive technical trend -- contrarian signal worth monitoring');
    }
  }

  return parts.length > 0 ? parts.join('. ') + '.' : 'No detailed sentiment data available.';
}

function getMoodBadgeClass(mood: string): string {
  const lower = mood.toLowerCase();
  if (lower.includes('very bullish')) return 'bg-green-600 text-white';
  if (lower.includes('bullish')) return 'bg-green-500 text-white';
  if (lower.includes('very bearish')) return 'bg-red-600 text-white';
  if (lower.includes('bearish')) return 'bg-red-500 text-white';
  return 'bg-gray-500 text-white';
}

// ============================================
// Prediction Market Helpers
// ============================================

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
// Dimension Bar Components
// ============================================

function DimensionBar({
  dimension,
  value,
}: {
  dimension: 'trend' | 'momentum' | 'volatility' | 'volume';
  value: number;
}) {
  const info = describeBreakdownValue(dimension, value);
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
              <div className="absolute left-1/2 top-0 h-full w-px bg-muted-foreground/20 z-10" />
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
// Dedicated Analysis Dimension Sections
// ============================================

/** Section 1: Overview / Summary -- always expanded */
function OverviewSection({
  insight,
  portfolioMatch,
  onSymbolClick,
}: {
  insight: DeepInsight;
  portfolioMatch?: { symbols: string[]; allocationPct?: number } | null;
  onSymbolClick: (symbol: string) => void;
}) {
  const actionInfo = actionConfig[insight.action];
  const ActionIcon = actionInfo.icon;

  return (
    <div
      className={cn(
        'rounded-xl border-l-4 bg-card/80 backdrop-blur-sm border border-border/50 overflow-hidden',
        'border-l-primary'
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-border/30 bg-primary/5">
        <div className="p-1.5 rounded-md bg-primary/10">
          <Layers className="h-4 w-4 text-primary" />
        </div>
        <span className="text-sm font-semibold text-foreground">Overview</span>
      </div>

      <div className="p-5 space-y-5">
        {/* Action + Title + Confidence */}
        <div className="flex flex-col lg:flex-row lg:items-start gap-4 lg:gap-6">
          <div className={cn('p-4 rounded-xl flex flex-col items-center justify-center min-w-[120px]', actionInfo.bgColor)}>
            <Badge className={cn('text-white text-sm px-4 py-2', actionInfo.color)}>
              <ActionIcon className="w-4 h-4 mr-2" />
              {actionInfo.label}
            </Badge>
          </div>

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
            <p className="text-base text-foreground font-medium leading-relaxed mb-2">
              {insight.thesis}
            </p>
            <p className="text-sm text-muted-foreground italic leading-relaxed">
              {laymanExplain(insight.thesis) ?? `In plain terms: This analysis recommends a "${actionConfig[insight.action].label}" position with ${Math.round(insight.confidence * 100)}% confidence over a ${insight.time_horizon.replace(/_/g, ' ')} timeframe.`}
            </p>
          </div>

          <div className="flex flex-col items-end gap-3">
            <ConfidenceGauge confidence={insight.confidence} />
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
        </div>

        {/* Time + Type + Date Metadata */}
        <div className="flex flex-wrap gap-6 pt-2 border-t border-border/30">
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">{insight.time_horizon.replace(/_/g, ' ')}</p>
              <p className="text-xs text-muted-foreground">Time Horizon</p>
            </div>
          </div>
          <div>
            <Badge variant="outline" className="capitalize">{insight.insight_type}</Badge>
            <p className="text-xs text-muted-foreground mt-1">Insight Type</p>
          </div>
          <div className="flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">{formatInsightDate(insight.created_at)}</p>
              <p className="text-xs text-muted-foreground">Analysis Date</p>
            </div>
          </div>
          {insight.updated_at && insight.updated_at !== insight.created_at && (
            <div className="flex items-center gap-2">
              <RefreshCw className="h-4 w-4 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium">{formatInsightDate(insight.updated_at)}</p>
                <p className="text-xs text-muted-foreground">Last Updated</p>
              </div>
            </div>
          )}
        </div>

        {/* Symbols */}
        <div className="pt-2 border-t border-border/30">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">Symbols</span>
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

        {/* Trading Parameters (if available) */}
        {(insight.entry_zone || insight.target_price || insight.stop_loss) && (
          <div className="pt-2 border-t border-border/30">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">Trading Parameters</span>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {insight.entry_zone && (
                <div className="rounded-lg bg-muted/30 px-3 py-2">
                  <span className="text-xs text-muted-foreground">Entry Zone</span>
                  <p className="text-sm font-semibold text-foreground">{insight.entry_zone}</p>
                </div>
              )}
              {insight.target_price && (
                <div className="rounded-lg bg-green-500/5 px-3 py-2">
                  <span className="text-xs text-green-600 dark:text-green-400">Target Price</span>
                  <p className="text-sm font-semibold text-green-600 dark:text-green-400">{insight.target_price}</p>
                </div>
              )}
              {insight.stop_loss && (
                <div className="rounded-lg bg-red-500/5 px-3 py-2">
                  <span className="text-xs text-red-600 dark:text-red-400">Stop Loss</span>
                  <p className="text-sm font-semibold text-red-600 dark:text-red-400">{insight.stop_loss}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Section: Technical Analysis */
function TechnicalAnalysisSection({
  insight,
  evidence,
}: {
  insight: DeepInsight;
  evidence: AnalystEvidence[];
}) {
  const ta = insight.technical_analysis_data;
  if (!ta) {
    if (evidence.length === 0) return null;
    // Show evidence-only section if we have analyst findings but no structured data
    return (
      <DimensionSectionCard dimension="technical" defaultOpen={true}>
        <p className="text-sm text-muted-foreground italic mb-3">
          Structured technical data is not available for this insight, but analyst findings are shown below.
        </p>
        <DimensionEvidence evidence={evidence} />
      </DimensionSectionCard>
    );
  }

  const ratingExplanation = buildTARatingExplanation(ta);
  const laymanSummary = buildTALaymanSummary(ta);
  const keyLevelsExplanation = buildKeyLevelsExplanation(ta);

  return (
    <DimensionSectionCard dimension="technical" defaultOpen={true} confidence={ta.confidence}>
      {/* Layman summary */}
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-4">
        {laymanSummary}
      </p>

      {/* Overall signal row */}
      <div className="flex items-start gap-3 flex-wrap mb-4">
        <Badge className={cn('text-sm px-4 py-1.5 font-semibold', getRatingBadgeClass(ta.rating))}>
          {ta.rating}
        </Badge>
        <div className="flex-1 min-w-[200px]">
          <p className="text-xs text-muted-foreground leading-relaxed">{ratingExplanation}</p>
        </div>
      </div>

      {/* Radar chart + dimension bars */}
      {ta.breakdown && (
        <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 items-start mb-4">
          <div className="flex justify-center">
            <TARadarChart breakdown={ta.breakdown} />
          </div>
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
        <div className="rounded-lg bg-muted/30 px-4 py-3 mb-4">
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
          {keyLevelsExplanation && (
            <p className="text-xs text-muted-foreground mt-2 leading-relaxed">{keyLevelsExplanation}</p>
          )}
        </div>
      )}

      {/* Signals */}
      {ta.signals && ta.signals.length > 0 && (
        <div className="mb-2">
          <span className="text-xs font-medium text-muted-foreground block mb-2">Active Signals</span>
          <div className="flex flex-wrap gap-1.5">
            {ta.signals.map((sig, i) => (
              <Tooltip key={i}>
                <TooltipTrigger asChild>
                  <Badge variant="outline" className="text-xs cursor-help">
                    {sig}
                  </Badge>
                </TooltipTrigger>
                <TooltipContent className="max-w-xs">
                  <p>{laymanExplain(sig) ?? sig}</p>
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        </div>
      )}

      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

/** Section: Macro Analysis */
function MacroAnalysisSection({
  insight,
  evidence,
}: {
  insight: DeepInsight;
  evidence: AnalystEvidence[];
}) {
  if (evidence.length === 0 && !insight.discovery_context) return null;

  const ctx = insight.discovery_context;
  const laymanSummary = ctx
    ? `The broader economy is in a "${ctx.macro_regime}" regime. ${
        ctx.macro_themes && ctx.macro_themes.length > 0
          ? `Key themes driving markets: ${ctx.macro_themes.join(', ')}.`
          : ''
      }`
    : evidence.length > 0
      ? 'Macro analysis examines the broader economic picture -- how interest rates, inflation, and economic growth affect this investment.'
      : '';

  return (
    <DimensionSectionCard dimension="macro" defaultOpen={evidence.length > 0}>
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-3">
        {laymanSummary}
      </p>

      {ctx && (
        <div className="space-y-3 mb-3">
          {ctx.macro_regime && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Economic Regime:</span>
              <Badge variant="outline" className={cn(
                ctx.macro_regime.toLowerCase().includes('risk-on') ? 'border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400' :
                ctx.macro_regime.toLowerCase().includes('risk-off') ? 'border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400' :
                'border-yellow-500/40 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400'
              )}>
                {ctx.macro_regime}
              </Badge>
            </div>
          )}
          {ctx.macro_themes && ctx.macro_themes.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground block mb-1.5">Key Themes</span>
              <div className="flex flex-wrap gap-1.5">
                {ctx.macro_themes.map((theme, i) => (
                  <Badge key={i} variant="secondary" className="text-xs">{theme}</Badge>
                ))}
              </div>
            </div>
          )}
          {ctx.top_sectors && ctx.top_sectors.length > 0 && (
            <div>
              <span className="text-xs text-muted-foreground block mb-1.5">Focus Sectors</span>
              <div className="flex flex-wrap gap-1.5">
                {ctx.top_sectors.map((sector, i) => (
                  <Badge key={i} variant="outline" className="text-xs text-purple-500 dark:text-purple-400 border-purple-500/20">{sector}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

/** Section: Sentiment */
function SentimentSection({
  insight,
  evidence,
}: {
  insight: DeepInsight;
  evidence: AnalystEvidence[];
}) {
  const sent = insight.sentiment_data;
  if (!sent && evidence.length === 0) return null;

  const ta = insight.technical_analysis_data;
  const laymanSummary = sent
    ? buildSentimentLaymanSummary(sent, ta)
    : 'Sentiment analysis tracks what retail traders and investors are saying on social media.';

  return (
    <DimensionSectionCard dimension="sentiment" defaultOpen={!!sent}>
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-3">
        {laymanSummary}
      </p>

      {sent && (
        <div className="space-y-4">
          {/* Overall mood */}
          {sent.overall_mood && (
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Overall Mood:</span>
                <Badge className={cn('text-sm px-3 py-1', getMoodBadgeClass(sent.overall_mood))}>
                  {sent.overall_mood}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground pl-1 leading-relaxed">
                {buildSentimentExplanation(sent, ta)}
              </p>
            </div>
          )}
          {!sent.overall_mood && !sent.trending?.length && !sent.per_symbol?.length && (
            <p className="text-xs text-muted-foreground italic">
              No sentiment data available -- social media monitoring did not return data for this analysis period.
            </p>
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
                    <div key={i}>
                      <div className="flex items-center gap-3 text-sm">
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
                      {sym.bullish_count != null && sym.bearish_count != null && (sym.bullish_count + sym.bearish_count) > 0 && (
                        <p className="text-[11px] text-muted-foreground/70 pl-[76px] mt-0.5">
                          {sym.bullish_count > sym.bearish_count * 2
                            ? `Strongly bullish skew (${sym.bullish_count} bullish vs ${sym.bearish_count} bearish posts)`
                            : sym.bearish_count > sym.bullish_count * 2
                              ? `Strongly bearish skew (${sym.bearish_count} bearish vs ${sym.bullish_count} bullish posts)`
                              : `Split sentiment (${sym.bullish_count} bullish, ${sym.bearish_count} bearish) -- no clear retail consensus`}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Source attribution */}
          <p className="text-[10px] text-muted-foreground/60 pt-2 border-t border-border/20">
            Source: r/wallstreetbets, r/stocks, r/investing. Sentiment scores derived from post analysis. Reddit sentiment can lag institutional positioning by hours to days.
          </p>
        </div>
      )}

      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

/** Section: Prediction Markets */
function PredictionMarketsSection({
  insight,
  evidence,
}: {
  insight: DeepInsight;
  evidence: AnalystEvidence[];
}) {
  const pred = insight.prediction_market_data;
  if (!pred && evidence.length === 0) return null;

  const laymanSummary = pred
    ? 'Prediction markets are platforms where people bet real money on future outcomes. Their prices reflect collective probability estimates, often considered more reliable than polls or expert forecasts.'
    : 'Prediction market data was not available for this analysis.';

  return (
    <DimensionSectionCard dimension="prediction" defaultOpen={!!pred}>
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-3">
        {laymanSummary}
      </p>

      {pred && (
        <div className="space-y-4">
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
            <div className="space-y-1">
              <ProbabilityBar
                label="Recession Risk (2026)"
                probability={pred.recession.probability_2026}
                source={pred.recession.source}
              />
              <p className="text-xs text-muted-foreground pl-1">
                {pred.recession.probability_2026 > 0.5
                  ? `At ${Math.round(pred.recession.probability_2026 * 100)}%, markets see recession as more likely than not -- risk-off positioning may be warranted`
                  : pred.recession.probability_2026 > 0.25
                    ? `At ${Math.round(pred.recession.probability_2026 * 100)}%, recession risk is elevated but not the base case -- monitor leading indicators`
                    : `At ${Math.round(pred.recession.probability_2026 * 100)}%, markets see low recession probability -- supportive of risk assets`}
              </p>
            </div>
          )}

          {/* Inflation */}
          {pred.inflation?.cpi_above_3pct != null && (
            <div className="space-y-1">
              <ProbabilityBar
                label="Inflation above 3%"
                probability={pred.inflation.cpi_above_3pct}
                source={pred.inflation.source}
              />
              <p className="text-xs text-muted-foreground pl-1">
                {pred.inflation.cpi_above_3pct > 0.5
                  ? `${Math.round(pred.inflation.cpi_above_3pct * 100)}% probability of CPI above 3% -- persistent inflation may delay rate cuts`
                  : `${Math.round(pred.inflation.cpi_above_3pct * 100)}% probability of CPI above 3% -- disinflation trend likely intact`}
              </p>
            </div>
          )}

          {/* GDP */}
          {pred.gdp?.q1_positive != null && (
            <div className="space-y-1">
              <ProbabilityBar
                label="Q1 GDP Growth (positive)"
                probability={pred.gdp.q1_positive}
                source={pred.gdp.source}
              />
              <p className="text-xs text-muted-foreground pl-1">
                {pred.gdp.q1_positive > 0.7
                  ? `${Math.round(pred.gdp.q1_positive * 100)}% chance of positive Q1 GDP -- strong growth expectations support equities`
                  : pred.gdp.q1_positive > 0.4
                    ? `${Math.round(pred.gdp.q1_positive * 100)}% chance of positive Q1 GDP -- growth outlook is uncertain`
                    : `Only ${Math.round(pred.gdp.q1_positive * 100)}% chance of positive Q1 GDP -- contraction fears are elevated`}
              </p>
            </div>
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

          {/* Data coverage note */}
          {(() => {
            const availableSources: string[] = [];
            if (pred.fed_rates?.next_meeting?.probabilities) availableSources.push('Fed rate probabilities');
            if (pred.recession?.probability_2026 != null) availableSources.push('recession risk');
            if (pred.inflation?.cpi_above_3pct != null) availableSources.push('inflation expectations');
            if (pred.gdp?.q1_positive != null) availableSources.push('GDP outlook');
            if (pred.sp500?.targets && pred.sp500.targets.length > 0) availableSources.push('S&P 500 targets');
            const allPossible = ['Fed rate probabilities', 'recession risk', 'inflation expectations', 'GDP outlook', 'S&P 500 targets'];
            const missing = allPossible.filter((s) => !availableSources.includes(s));
            if (missing.length > 0 && missing.length < allPossible.length) {
              return (
                <p className="text-xs text-muted-foreground/70 italic pt-2 border-t border-border/20">
                  Limited prediction market data -- missing: {missing.join(', ')}. Available data may not fully represent market consensus.
                </p>
              );
            }
            return null;
          })()}
        </div>
      )}

      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

/** Section: Risk Assessment */
function RiskAssessmentSection({
  insight,
  evidence,
}: {
  insight: DeepInsight;
  evidence: AnalystEvidence[];
}) {
  if (insight.risk_factors.length === 0 && !insight.invalidation_trigger && evidence.length === 0) return null;

  const riskLevel = insight.risk_factors.length >= 4 ? 'high' : insight.risk_factors.length >= 2 ? 'moderate' : 'low';
  const laymanSummary = `Risk level is ${riskLevel}. ${
    insight.risk_factors.length > 0
      ? `The biggest concern is: ${insight.risk_factors[0]}.`
      : 'No specific risk factors identified.'
  } ${insight.invalidation_trigger ? `This thesis is invalidated if: ${insight.invalidation_trigger}` : ''}`;

  return (
    <DimensionSectionCard dimension="risk" defaultOpen={insight.risk_factors.length > 0}>
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-3">
        {laymanSummary}
      </p>

      {insight.risk_factors.length > 0 && (
        <div className="mb-3">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">Risk Factors</span>
          <ul className="space-y-2">
            {insight.risk_factors.map((risk, i) => (
              <li key={i} className="flex items-start gap-2 text-sm">
                <AlertTriangle className="h-3.5 w-3.5 text-rose-500 mt-0.5 shrink-0" />
                <span className="text-foreground">{risk}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {insight.invalidation_trigger && (
        <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 px-4 py-3 mb-3">
          <span className="text-xs font-medium text-rose-600 dark:text-rose-400 block mb-1">Invalidation Trigger</span>
          <p className="text-sm text-foreground">{insight.invalidation_trigger}</p>
          <p className="text-xs text-muted-foreground italic mt-1">
            If this condition is met, the entire thesis should be reconsidered.
          </p>
        </div>
      )}

      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

/** Section: Correlation Analysis */
function CorrelationSection({
  evidence,
}: {
  evidence: AnalystEvidence[];
}) {
  if (evidence.length === 0) return null;

  return (
    <DimensionSectionCard dimension="correlation" defaultOpen={evidence.length > 0}>
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-3">
        Correlation analysis looks at how different stocks and assets move relative to each other. When assets that normally move together start diverging, it can signal a trading opportunity.
      </p>
      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

/** Section: Sector Analysis */
function SectorSection({
  insight,
  evidence,
}: {
  insight: DeepInsight;
  evidence: AnalystEvidence[];
}) {
  if (evidence.length === 0 && !insight.discovery_context?.top_sectors?.length) return null;

  const ctx = insight.discovery_context;
  const laymanSummary = ctx?.top_sectors?.length
    ? `Sector analysis focuses on industry-level trends. Currently favored sectors: ${ctx.top_sectors.join(', ')}.`
    : 'Sector analysis examines how broader industry trends affect this specific investment.';

  return (
    <DimensionSectionCard dimension="sector" defaultOpen={evidence.length > 0}>
      <p className="text-sm text-muted-foreground italic leading-relaxed mb-3">
        {laymanSummary}
      </p>

      {ctx?.top_sectors && ctx.top_sectors.length > 0 && (
        <div className="mb-3">
          <span className="text-xs font-medium text-muted-foreground block mb-1.5">Top Sectors</span>
          <div className="flex flex-wrap gap-1.5">
            {ctx.top_sectors.map((sector, i) => (
              <Badge key={i} variant="outline" className="text-xs text-emerald-500 dark:text-emerald-400 border-emerald-500/20">{sector}</Badge>
            ))}
          </div>
        </div>
      )}

      <DimensionEvidence evidence={evidence} />
    </DimensionSectionCard>
  );
}

// ============================================
// Insight Details Panel (Redesigned)
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
  // Group supporting evidence by dimension
  const evidenceByDimension = useMemo(() => {
    const grouped: Record<AnalysisDimensionType, AnalystEvidence[]> = {
      technical: [],
      macro: [],
      sector: [],
      risk: [],
      correlation: [],
      sentiment: [],
      prediction: [],
    };
    const ungrouped: AnalystEvidence[] = [];

    for (const ev of insight.supporting_evidence) {
      const dim = analystToDimension(ev.analyst);
      if (dim) {
        grouped[dim].push(ev);
      } else {
        ungrouped.push(ev);
      }
    }
    return { grouped, ungrouped };
  }, [insight.supporting_evidence]);

  return (
    <TooltipProvider>
      <div className="space-y-5">
        {/* 1. Overview Section -- always expanded */}
        <OverviewSection
          insight={insight}
          portfolioMatch={portfolioMatch}
          onSymbolClick={onSymbolClick}
        />

        {/* 2. Technical Analysis Section */}
        <TechnicalAnalysisSection
          insight={insight}
          evidence={evidenceByDimension.grouped.technical}
        />

        {/* 3. Macro Analysis Section */}
        <MacroAnalysisSection
          insight={insight}
          evidence={evidenceByDimension.grouped.macro}
        />

        {/* 4. Sentiment Section */}
        <SentimentSection
          insight={insight}
          evidence={evidenceByDimension.grouped.sentiment}
        />

        {/* 5. Prediction Markets Section */}
        <PredictionMarketsSection
          insight={insight}
          evidence={evidenceByDimension.grouped.prediction}
        />

        {/* 6. Risk Assessment Section */}
        <RiskAssessmentSection
          insight={insight}
          evidence={evidenceByDimension.grouped.risk}
        />

        {/* 7. Correlation Analysis Section */}
        <CorrelationSection
          evidence={evidenceByDimension.grouped.correlation}
        />

        {/* 8. Sector Analysis Section */}
        <SectorSection
          insight={insight}
          evidence={evidenceByDimension.grouped.sector}
        />

        {/* Ungrouped evidence (analysts that don't match any dimension) */}
        {evidenceByDimension.ungrouped.length > 0 && (
          <div className="rounded-xl border bg-card/80 backdrop-blur-sm border-border/50 overflow-hidden">
            <div className="flex items-center gap-3 px-5 py-4 border-b border-border/30 bg-muted/30">
              <Users className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold text-foreground">Additional Analyst Findings</span>
            </div>
            <div className="p-5 space-y-2">
              {evidenceByDimension.ungrouped.map((ev, i) => (
                <div key={i} className="flex items-start gap-3">
                  <Badge variant="outline" className="capitalize shrink-0 text-xs">{ev.analyst}</Badge>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-foreground">{ev.finding}</p>
                    {laymanExplain(ev.finding) != null && (
                      <p className="text-xs text-muted-foreground italic mt-0.5">{laymanExplain(ev.finding)}</p>
                    )}
                  </div>
                  {ev.confidence != null && (
                    <span className="text-xs text-muted-foreground shrink-0">{Math.round(ev.confidence * 100)}%</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Statistical Signals for Primary Symbol */}
        {insight.primary_symbol && (
          <StatisticalSignalsCard
            symbol={insight.primary_symbol}
            maxSignals={5}
            className="bg-card/80 backdrop-blur-sm border-border/50"
          />
        )}

        {/* Historical Precedent */}
        {insight.historical_precedent && (
          <div className="rounded-xl border bg-card/80 backdrop-blur-sm border-border/50 overflow-hidden">
            <div className="flex items-center gap-3 px-5 py-4 border-b border-border/30 bg-muted/30">
              <History className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold text-foreground">Historical Precedent</span>
            </div>
            <div className="p-5">
              <p className="text-sm text-foreground leading-relaxed">{insight.historical_precedent}</p>
              <p className="text-xs text-muted-foreground italic mt-2">
                Historical patterns do not guarantee future results, but they can provide useful context.
              </p>
            </div>
          </div>
        )}

        {/* Discovery Context (if not already shown in macro section) */}
        {insight.discovery_context && (
          <DiscoveryContextCard
            context={insight.discovery_context}
            className="bg-card/80 backdrop-blur-sm border-border/50"
          />
        )}

        {/* Metadata */}
        <div className="flex flex-wrap gap-6 text-sm text-muted-foreground px-1">
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

        {/* Refresh Button */}
        <div className="pt-2">
          <Button variant="outline" onClick={onRefresh} disabled={isRefreshing}>
            <RefreshCw className={cn('h-4 w-4 mr-2', isRefreshing && 'animate-spin')} />
            {isRefreshing ? 'Refreshing...' : 'Refresh Data'}
          </Button>
        </div>
      </div>
    </TooltipProvider>
  );
}

// ============================================
// Conversations Panel (unchanged)
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
    queryClient.invalidateQueries({ queryKey: deepInsightKeys.detail(insightId) });
  }, [queryClient, insightId]);

  const handleResearchLaunched = useCallback((researchId: number) => {
    console.log('Research launched:', researchId);
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
          <Card className="bg-card/80 backdrop-blur-sm border-border/50">
            <CardContent className="pt-6">
              <InsightDetailsSkeleton />
            </CardContent>
          </Card>
          <Card className="h-[600px] bg-card/80 backdrop-blur-sm border-border/50">
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
        <Card className="py-12 bg-card/80 backdrop-blur-sm border-border/50">
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
        <div>
          <ScrollArea className="h-[calc(100vh-200px)] pr-4">
            <InsightDetailsPanel
              insight={insight}
              onRefresh={handleRefresh}
              isRefreshing={isFetching}
              onSymbolClick={handleSymbolClick}
              portfolioMatch={portfolioMatch}
            />
          </ScrollArea>
        </div>

        {/* Right Column: Conversations */}
        <Card className="h-[calc(100vh-200px)] flex flex-col bg-card/80 backdrop-blur-sm border-border/50">
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
