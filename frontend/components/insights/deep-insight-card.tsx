'use client';

import { useState } from 'react';
import {
  TrendingUp, TrendingDown, Minus, AlertTriangle, Clock,
  ChevronDown, ChevronUp, Target, Shield, History, Users, CalendarClock,
  DollarSign, ArrowUpRight, ArrowDownRight, MessageSquare, GitBranch,
  Globe, PieChart, Activity, Zap
} from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { TooltipProvider, Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { DeepInsight, InsightAction } from '@/types';
import { OutcomeBadge } from './outcome-badge';
import { useInsightConversations } from '@/lib/hooks/use-insight-conversation';
import { cn } from '@/lib/utils';

// ============================================
// Design System Constants
// ============================================

/** Analyst type color mapping */
const analystColors: Record<string, {
  border: string;
  bg: string;
  text: string;
  badge: string;
  progress: string;
  icon: typeof TrendingUp;
}> = {
  technical: {
    border: 'border-l-blue-500',
    bg: 'bg-blue-500/10',
    text: 'text-blue-500 dark:text-blue-400',
    badge: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30',
    progress: 'bg-blue-500',
    icon: TrendingUp,
  },
  macro: {
    border: 'border-l-purple-500',
    bg: 'bg-purple-500/10',
    text: 'text-purple-500 dark:text-purple-400',
    badge: 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30',
    progress: 'bg-purple-500',
    icon: Globe,
  },
  sector: {
    border: 'border-l-emerald-500',
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-500 dark:text-emerald-400',
    badge: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
    progress: 'bg-emerald-500',
    icon: PieChart,
  },
  risk: {
    border: 'border-l-rose-500',
    bg: 'bg-rose-500/10',
    text: 'text-rose-500 dark:text-rose-400',
    badge: 'bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30',
    progress: 'bg-rose-500',
    icon: Shield,
  },
  correlation: {
    border: 'border-l-amber-500',
    bg: 'bg-amber-500/10',
    text: 'text-amber-500 dark:text-amber-400',
    badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30',
    progress: 'bg-amber-500',
    icon: GitBranch,
  },
  sentiment: {
    border: 'border-l-cyan-500',
    bg: 'bg-cyan-500/10',
    text: 'text-cyan-500 dark:text-cyan-400',
    badge: 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 border-cyan-500/30',
    progress: 'bg-cyan-500',
    icon: Activity,
  },
  prediction: {
    border: 'border-l-violet-500',
    bg: 'bg-violet-500/10',
    text: 'text-violet-500 dark:text-violet-400',
    badge: 'bg-violet-500/15 text-violet-700 dark:text-violet-300 border-violet-500/30',
    progress: 'bg-violet-500',
    icon: Zap,
  },
};

/** Fallback for unknown analyst types */
const defaultAnalystColor = {
  border: 'border-l-gray-400',
  bg: 'bg-gray-500/10',
  text: 'text-gray-500 dark:text-gray-400',
  badge: 'bg-gray-500/15 text-gray-700 dark:text-gray-300 border-gray-500/30',
  progress: 'bg-gray-500',
  icon: Users,
};

/** Map analyst name strings to a known type key */
function getAnalystType(analyst: string): string {
  const lower = analyst.toLowerCase();
  if (lower.includes('technical') || lower.includes('ta_')) return 'technical';
  if (lower.includes('macro') || lower.includes('economy') || lower.includes('economic')) return 'macro';
  if (lower.includes('sector') || lower.includes('rotation')) return 'sector';
  if (lower.includes('risk') || lower.includes('portfolio_risk')) return 'risk';
  if (lower.includes('correlation') || lower.includes('cross') || lower.includes('intermarket')) return 'correlation';
  if (lower.includes('sentiment') || lower.includes('social') || lower.includes('crowd')) return 'sentiment';
  if (lower.includes('prediction') || lower.includes('forecast') || lower.includes('probability')) return 'prediction';
  return 'technical'; // default fallback
}

function getAnalystColorConfig(analyst: string) {
  const type = getAnalystType(analyst);
  return analystColors[type] || defaultAnalystColor;
}

/** Action badge configuration */
const actionConfig: Record<InsightAction, {
  color: string;
  borderColor: string;
  icon: typeof TrendingUp;
  label: string;
}> = {
  STRONG_BUY: { color: 'bg-green-600 text-white', borderColor: 'border-l-green-600', icon: TrendingUp, label: 'Strong Buy' },
  BUY: { color: 'bg-green-500 text-white', borderColor: 'border-l-green-500', icon: TrendingUp, label: 'Buy' },
  HOLD: { color: 'bg-yellow-500 text-white', borderColor: 'border-l-yellow-500', icon: Minus, label: 'Hold' },
  SELL: { color: 'bg-red-500 text-white', borderColor: 'border-l-red-500', icon: TrendingDown, label: 'Sell' },
  STRONG_SELL: { color: 'bg-red-600 text-white', borderColor: 'border-l-red-600', icon: TrendingDown, label: 'Strong Sell' },
  WATCH: { color: 'bg-blue-500 text-white', borderColor: 'border-l-blue-500', icon: Target, label: 'Watch' },
};

// ============================================
// Layman Explanation Utility
// ============================================

/** Extract all stock symbols ($XXX or standalone 2-5 letter uppercase) from text */
function extractSymbols(text: string): string[] {
  const matches = text.match(/\b[A-Z]{2,5}\b/g) || [];
  const stopWords = new Set(['VaR', 'RSI', 'MACD', 'SMA', 'EMA', 'GDP', 'CPI', 'THE', 'AND', 'FOR', 'NOT', 'BUT', 'ALL', 'WITH', 'THIS', 'THAT']);
  return [...new Set(matches.filter(m => !stopWords.has(m)))];
}

/** Extract all percentages from text */
function extractPercentages(text: string): string[] {
  return (text.match(/[\d.]+%/g) || []);
}

/** Extract dollar amounts from text */
function extractDollarAmounts(text: string): string[] {
  return (text.match(/\$[\d,.]+/g) || []);
}

/**
 * Tier 1: Full-sentence pattern matching.
 * Detects the overall MEANING of the sentence and produces a complete rewrite.
 */
const sentencePatterns: Array<{
  test: (text: string) => RegExpMatchArray | null;
  rewrite: (match: RegExpMatchArray, text: string) => string;
}> = [
  // Late-cycle/mid-cycle/early-cycle with recession + stagflation probabilities
  {
    test: (t) => t.match(/(late|mid|early)[- ]cycle.*?(\d+)%\s*(?:confidence|prob).*?(\d+)%\s*recession.*?(\d+)%\s*stagflation/i),
    rewrite: (m) => {
      const phase = m[1].toLowerCase();
      const phraseLookup: Record<string, string> = { late: 'running out of steam', mid: 'in the middle of its growth phase', early: 'in the early stages of recovery' };
      const phasePhrase = phraseLookup[phase] || 'at a turning point';
      const recession = parseInt(m[3]);
      const stagflation = parseInt(m[4]);
      const recessionDesc = recession === 50 ? 'a coin-flip chance' : recession > 60 ? `a high ${recession}% chance` : `about a ${recession}% chance`;
      return `The economy looks like it's ${phasePhrase}. There's ${recessionDesc} we enter a recession, and about 1-in-${Math.round(100 / stagflation)} odds of stagflation (prices rising while the economy stalls). Both scenarios would hit growth-oriented investments hardest.`;
    },
  },
  // Late-cycle/mid-cycle/early-cycle with recession probability only
  {
    test: (t) => t.match(/(late|mid|early)[- ]cycle.*?(\d+)%\s*(?:confidence|prob).*?(\d+)%\s*recession/i),
    rewrite: (m) => {
      const phase = m[1].toLowerCase();
      const phraseLookup: Record<string, string> = { late: 'running out of steam', mid: 'in the middle of its growth phase', early: 'in the early stages of recovery' };
      const phasePhrase = phraseLookup[phase] || 'at a turning point';
      const recession = parseInt(m[3]);
      const recessionDesc = recession === 50 ? 'a coin-flip chance' : recession > 60 ? `a high ${recession}% chance` : `about a ${recession}% chance`;
      return `The economy looks like it's ${phasePhrase}. There's ${recessionDesc} of a recession, which would be bad news for most stock portfolios.`;
    },
  },
  // Late-cycle/mid-cycle/early-cycle with just confidence
  {
    test: (t) => t.match(/(late|mid|early)[- ]cycle.*?(\d+)%\s*confidence/i),
    rewrite: (m) => {
      const phase = m[1].toLowerCase();
      const phraseLookup: Record<string, string> = { late: 'nearing the end of its growth cycle, which often means increased volatility ahead', mid: 'in the middle of its growth phase, which is generally a stable period for stocks', early: 'in the early stages of recovery, which is often a good time for riskier investments' };
      return `The economy appears to be ${phraseLookup[phase] || 'at a turning point'}.`;
    },
  },
  // VaR with range
  {
    test: (t) => t.match(/VaR\s*([\d.]+)[-–]([\d.]+)%/i),
    rewrite: (m, text) => {
      const low = m[1];
      const high = m[2];
      const hasConcentration = /concentrat|cluster|correlat/i.test(text);
      let result = `On a bad day, your portfolio could drop ${low}-${high}%.`;
      if (hasConcentration) {
        result += ' This is higher than normal because your investments are bunched together in similar stocks -- if one falls, they\'ll likely all fall.';
      } else {
        result += ' This kind of loss happens roughly 1 in 20 trading days.';
      }
      return result;
    },
  },
  // VaR single value
  {
    test: (t) => t.match(/VaR\s*([\d.]+)%/i),
    rewrite: (m) => `On a bad day, your portfolio could drop about ${m[1]}%. This kind of loss happens roughly 1 in 20 trading days.`,
  },
  // Squeeze clustering + parabolic clustering = synchronized risk
  {
    test: (t) => t.match(/squeeze.*?clustering.*?\(([^)]+)\).*?parabolic.*?clustering.*?\(([^)]+)\)/i),
    rewrite: (m) => {
      const squeezeSyms = m[1].trim();
      const parabolicSyms = m[2].trim();
      return `${squeezeSyms} are coiling up for a big move -- like a compressed spring that could snap either way. Meanwhile, ${parabolicSyms} have been rising at an unsustainable pace. The risk is that these all unwind at the same time.`;
    },
  },
  // Distribution signals + squeeze uncertainty
  {
    test: (t) => t.match(/distribution\s+signals?\s*\(([^)]+)\).*?squeeze\s+(?:uncertainty|signals?)\s*\(([^)]+)\)/i),
    rewrite: (m) => `It looks like big investors may be quietly selling ${m[1].trim()} while prices are still high. ${m[2].trim()} are in a holding pattern where a big price swing is brewing, but the direction isn't clear yet.`,
  },
  // Distribution signals alone
  {
    test: (t) => t.match(/distribution\s+signals?\s*\(([^)]+)\)/i),
    rewrite: (m) => `It looks like big investors may be quietly selling ${m[1].trim()} while prices are still high. This often happens before a noticeable price decline.`,
  },
  // RSI divergence + MACD crossover + support level
  {
    test: (t) => t.match(/RSI\s+divergence.*MACD\s+(?:bearish\s+)?crossover.*support\s+(?:at\s+)?\$?([\d,.]+)/i),
    rewrite: (m) => `The stock's momentum is fading even as the price holds steady -- a warning sign. The trend indicators just flipped negative, and the price is sitting right at a critical floor of $${m[1]}. If it drops below, expect a bigger decline.`,
  },
  // RSI divergence + MACD crossover (no support)
  {
    test: (t) => t.match(/RSI\s+divergence.*MACD\s+(?:bearish\s+)?crossover/i),
    rewrite: () => 'The stock\'s momentum is fading even though the price hasn\'t dropped yet -- a warning sign. The trend indicators just flipped negative, which often precedes a price decline.',
  },
  // RSI divergence + MACD bullish crossover
  {
    test: (t) => t.match(/RSI\s+divergence.*MACD\s+bullish\s+crossover/i),
    rewrite: () => 'The stock is building momentum under the surface, even though the price hasn\'t moved much yet. The trend indicators just flipped positive, suggesting a rally may be starting.',
  },
  // Squeeze clustering alone
  {
    test: (t) => t.match(/squeeze\s+(?:clustering|setup)\s*\(([^)]+)\)/i),
    rewrite: (m) => `${m[1].trim()} are coiling up for a big move -- like a compressed spring. When it snaps, expect a sharp price swing in one direction, but it's not clear which way yet.`,
  },
  // Parabolic clustering alone
  {
    test: (t) => t.match(/parabolic\s+(?:clustering|move|rise|signal)\s*\(([^)]+)\)/i),
    rewrite: (m) => `${m[1].trim()} have been rising at an unsustainable pace -- like a ball thrown straight up, they'll eventually come back down. The timing is uncertain, but the risk is real.`,
  },
  // RSI with specific value
  {
    test: (t) => t.match(/RSI\s*(?:at|above|below|near|of|is)?\s*(\d+)/i),
    rewrite: (m, text) => {
      const val = parseInt(m[1]);
      const symbols = extractSymbols(text);
      const subject = symbols.length > 0 ? symbols[0] : 'The stock';
      if (val >= 70) return `${subject}'s price has been running hot -- the momentum gauge reads ${val} out of 100. When it gets this high, the stock often pulls back for a breather.`;
      if (val <= 30) return `${subject}'s price has been beaten down -- the momentum gauge reads just ${val} out of 100. When it gets this low, the stock often bounces back.`;
      return `${subject}'s momentum is in a neutral zone at ${val}, meaning there's no strong push in either direction right now.`;
    },
  },
  // MACD bearish crossover
  {
    test: (t) => t.match(/MACD\s+bearish\s+cross(?:over)?/i),
    rewrite: () => 'A key trend indicator just flipped negative. Think of it like a traffic light turning yellow -- the upward momentum is fading and caution is warranted.',
  },
  // MACD bullish crossover
  {
    test: (t) => t.match(/MACD\s+(?:bullish\s+)?cross(?:over)?/i),
    rewrite: () => 'A key trend indicator just flipped positive. This suggests the downward pressure is easing and the stock may be starting to turn around.',
  },
  // MACD divergence
  {
    test: (t) => t.match(/MACD\s+divergence/i),
    rewrite: () => 'The price and a key trend indicator are telling different stories. This disconnect often signals that the current trend is running out of gas and a reversal may be coming.',
  },
  // Support at price level
  {
    test: (t) => t.match(/(?:testing|near|at|approaching)?\s*(?:key\s+)?support\s+(?:at|near|around|level|of)?\s*\$?([\d,.]+)/i),
    rewrite: (m) => `The price is sitting near a critical floor of $${m[1]}. This is a level where buyers have stepped in before. If it holds, the stock could bounce; if it breaks, expect a sharper drop.`,
  },
  // Resistance at price level
  {
    test: (t) => t.match(/(?:testing|near|at|approaching)?\s*(?:key\s+)?resistance\s+(?:at|near|around|level|of)?\s*\$?([\d,.]+)/i),
    rewrite: (m) => `The price is bumping up against a ceiling around $${m[1]}. This is a level where sellers have cashed out before. Breaking through it would be a bullish sign; failing here could mean a pullback.`,
  },
  // Breakout above
  {
    test: (t) => t.match(/break(?:out|ing\s+out)\s+(?:above|from|through)\s*\$?([\d,.]+)?/i),
    rewrite: (m) => {
      const level = m[1];
      return level
        ? `The price just punched through a key ceiling at $${level}. This kind of breakout often attracts new buyers and can lead to further gains.`
        : 'The price just broke through a key ceiling. This kind of breakout often attracts new buyers and can lead to further gains.';
    },
  },
  // Breakdown below
  {
    test: (t) => t.match(/break(?:down|ing\s+down)\s+(?:below|from|through)\s*\$?([\d,.]+)?/i),
    rewrite: (m) => {
      const level = m[1];
      return level
        ? `The price just fell through a key floor at $${level}. This kind of breakdown often triggers more selling and can accelerate the decline.`
        : 'The price just fell through a key floor. This kind of breakdown often triggers more selling and can accelerate the decline.';
    },
  },
  // Recession probability standalone
  {
    test: (t) => t.match(/(\d+)%\s*(?:recession|chance of recession|recession prob)/i),
    rewrite: (m) => {
      const pct = parseInt(m[1]);
      if (pct >= 70) return `There's a ${pct}% chance of a recession, which means the economy would shrink and jobs would be harder to find. This would be bad for most investments.`;
      if (pct >= 40) return `There's a meaningful ${pct}% chance of a recession -- not a sure thing, but high enough that it's worth being cautious with riskier investments.`;
      return `Recession risk is relatively low at ${pct}%, meaning the economy is expected to keep growing for now.`;
    },
  },
  // Stagflation
  {
    test: (t) => t.match(/stagflation/i),
    rewrite: (_, text) => {
      const pcts = extractPercentages(text);
      const probPart = pcts.length > 0 ? ` (${pcts[0]} probability)` : '';
      return `There's a risk of stagflation${probPart} -- that's when prices keep rising but the economy stalls. It's one of the worst scenarios for investors because everything gets more expensive while growth disappears.`;
    },
  },
  // Market breadth narrowing/declining
  {
    test: (t) => t.match(/(?:market\s+)?breadth\s+(?:narrowing|declining|weakening|deteriorating)/i),
    rewrite: () => 'Fewer and fewer stocks are participating in the rally. It\'s like a parade where most of the marchers have dropped out -- the ones still going may not last much longer either.',
  },
  // Market breadth improving
  {
    test: (t) => t.match(/(?:market\s+)?breadth\s+(?:improving|expanding|strengthening)/i),
    rewrite: () => 'More stocks are joining the rally, which is a healthy sign. When lots of stocks rise together (not just the big names), it suggests the uptrend has staying power.',
  },
  // Momentum fading/divergence
  {
    test: (t) => t.match(/momentum\s+(?:divergence|weakening|fading|stalling)/i),
    rewrite: () => 'The speed of price moves is slowing down. The stock is still moving in its current direction, but it\'s losing energy -- like a car coasting after taking its foot off the gas.',
  },
  // Regime change/shift
  {
    test: (t) => t.match(/(?:market\s+)?regime\s+(?:change|shift|transition)/i),
    rewrite: () => 'The overall market environment is fundamentally changing. Strategies that worked recently may stop working, and it\'s a good time to reassess what you own.',
  },
  // Mean reversion
  {
    test: (t) => t.match(/mean\s+reversion/i),
    rewrite: () => 'Prices have stretched far from their normal range and may snap back, like a rubber band being pulled. Historically, extreme moves tend to partially reverse.',
  },
  // Volatility expansion/spike
  {
    test: (t) => t.match(/volatility\s+(?:expansion|spike|surge)/i),
    rewrite: () => 'Market swings are getting bigger than usual. Expect larger daily price moves in both directions -- this means both bigger gains and bigger losses are possible.',
  },
  // Volatility contraction/compression
  {
    test: (t) => t.match(/volatility\s+(?:contraction|compression|low)/i),
    rewrite: () => 'The market has been unusually calm with small price moves. This kind of quiet often comes before a sharp move -- like the calm before a storm.',
  },
  // Yield curve inverted
  {
    test: (t) => t.match(/(?:yield\s+curve\s+)?invert(?:ed|ion)/i),
    rewrite: () => 'Short-term bonds are paying more than long-term ones, which is unusual. Historically, this has been one of the most reliable warning signs that a recession is coming within the next year or two.',
  },
  // Yield curve steepening
  {
    test: (t) => t.match(/yield\s+curve\s+steepening/i),
    rewrite: () => 'The gap between short and long-term interest rates is widening. This typically signals that the market expects economic growth to pick up.',
  },
  // Head and shoulders
  {
    test: (t) => t.match(/head\s+and\s+shoulders/i),
    rewrite: () => 'The price chart has formed a distinctive pattern that often appears before a significant downturn. It\'s one of the most well-known reversal signals in technical analysis.',
  },
  // Golden cross
  {
    test: (t) => t.match(/golden\s+cross/i),
    rewrite: () => 'A rare bullish signal just appeared: the short-term trend crossed above the long-term trend. Historically, this has preceded extended rallies.',
  },
  // Death cross
  {
    test: (t) => t.match(/death\s+cross/i),
    rewrite: () => 'A bearish signal just appeared: the short-term trend crossed below the long-term trend. This has historically preceded extended declines, though it can sometimes be a false alarm.',
  },
  // Accumulation
  {
    test: (t) => t.match(/accumulation\s+(?:phase|signals?|pattern)/i),
    rewrite: () => 'Large investors appear to be quietly buying. They\'re building positions while the price is still low, which is often an early sign that the stock will eventually move higher.',
  },
  // Double top
  {
    test: (t) => t.match(/double\s+top/i),
    rewrite: (_, text) => {
      const prices = extractDollarAmounts(text);
      const level = prices.length > 0 ? ` near ${prices[0]}` : '';
      return `The price tried to break higher twice${level} and failed both times. This "double top" pattern often signals that the stock has hit its ceiling and may head lower.`;
    },
  },
  // Double bottom
  {
    test: (t) => t.match(/double\s+bottom/i),
    rewrite: (_, text) => {
      const prices = extractDollarAmounts(text);
      const level = prices.length > 0 ? ` near ${prices[0]}` : '';
      return `The price bounced off the same floor twice${level}. This "double bottom" pattern often signals that the worst is over and the stock may start recovering.`;
    },
  },
];

/**
 * Translate technical market jargon into plain English.
 *
 * Uses a tiered approach:
 * - Tier 1: Full-sentence pattern matching for complete rewrites
 * - Tier 2: Analyst-type contextual rewrite with extracted data
 * - Tier 3: Generic simplification fallback
 */
export function getLaymanExplanation(analystType: string, technicalText: string): string {
  if (!technicalText || technicalText.trim().length === 0) {
    return 'No additional details provided.';
  }

  // Tier 1: Try full-sentence pattern rewrites
  for (const { test, rewrite } of sentencePatterns) {
    const match = test(technicalText);
    if (match) {
      return rewrite(match, technicalText);
    }
  }

  // Tier 2: Analyst-type contextual rewrite with extracted data
  const type = getAnalystType(analystType);
  const symbols = extractSymbols(technicalText);
  const percentages = extractPercentages(technicalText);
  const prices = extractDollarAmounts(technicalText);

  const symbolPhrase = symbols.length > 0 ? ` for ${symbols.slice(0, 3).join(', ')}` : '';
  const pctPhrase = percentages.length > 0 ? ` Key numbers: ${percentages.slice(0, 3).join(', ')}.` : '';
  const pricePhrase = prices.length > 0 ? ` Key prices: ${prices.slice(0, 2).join(', ')}.` : '';

  const tier2Rewrites: Record<string, string> = {
    technical: `The chart patterns and price trends${symbolPhrase} are showing a notable signal.${pctPhrase}${pricePhrase} This is worth watching as it may indicate where the price is headed next.`,
    macro: `Looking at the broader economy, conditions are shifting in a way that could affect your investments${symbolPhrase}.${pctPhrase} Keep an eye on how this develops over the coming weeks.`,
    sector: `Industry-level trends are signaling a shift${symbolPhrase}.${pctPhrase} Some sectors are gaining favor while others are falling out -- this can create opportunities.`,
    risk: `From a risk perspective, there are signals${symbolPhrase} that warrant attention.${pctPhrase}${pricePhrase} This doesn't mean something bad will happen, but it's worth being prepared.`,
    correlation: `Looking at how these investments move together${symbolPhrase}, an unusual pattern has emerged.${pctPhrase} When normally-linked assets start behaving differently, it often signals a change is coming.`,
    sentiment: `Market sentiment${symbolPhrase} is sending a signal worth noting.${pctPhrase} What other investors are thinking and doing can influence where prices head next.`,
    prediction: `Looking at where prediction markets see things headed${symbolPhrase}: the odds are notable.${pctPhrase} These markets aggregate many bettors' views and tend to be reasonably accurate.`,
  };

  if (tier2Rewrites[type]) {
    return tier2Rewrites[type];
  }

  // Tier 3: Generic fallback
  const dataParts: string[] = [];
  if (symbols.length > 0) dataParts.push(`involving ${symbols.slice(0, 3).join(', ')}`);
  if (percentages.length > 0) dataParts.push(`with key figures of ${percentages.slice(0, 2).join(' and ')}`);
  if (prices.length > 0) dataParts.push(`at price levels of ${prices.slice(0, 2).join(' and ')}`);

  const dataPhrase = dataParts.length > 0 ? ` ${dataParts.join(', ')}` : '';
  return `This analyst spotted something noteworthy${dataPhrase}. It's a signal that could affect your investment decisions going forward.`;
}

// ============================================
// Helper Components
// ============================================

interface DeepInsightCardProps {
  insight: DeepInsight;
  onSymbolClick?: (symbol: string) => void;
  onClick?: () => void;
  onChatClick?: (insightId: number) => void;
  parentInsightTitle?: string;
}

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

/** Confidence gauge: a small colored arc/progress indicator */
function ConfidenceGauge({ value, className }: { value: number; className?: string }) {
  const pct = Math.round(value * 100);
  const color = pct >= 75 ? 'text-green-500' : pct >= 50 ? 'text-yellow-500' : 'text-red-500';
  const strokeColor = pct >= 75 ? '#22c55e' : pct >= 50 ? '#eab308' : '#ef4444';
  const bgStroke = 'rgba(128,128,128,0.2)';

  // SVG arc parameters
  const size = 52;
  const strokeWidth = 5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div className={cn('relative inline-flex items-center justify-center', className)}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={bgStroke}
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="transition-all duration-500"
        />
      </svg>
      <span className={cn('absolute text-xs font-bold', color)}>
        {pct}%
      </span>
    </div>
  );
}

/** Thin colored progress bar for analyst confidence */
function ThinConfidenceBar({ value, colorClass }: { value: number; colorClass: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden mt-1.5">
      <div
        className={cn('h-full rounded-full transition-all duration-500', colorClass)}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/** Format analyst name for display: snake_case -> Title Case, trim common suffixes */
function formatAnalystName(analyst: string): string {
  return analyst
    .replace(/_analyst$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

// ============================================
// Main Component
// ============================================

export function DeepInsightCard({ insight, onSymbolClick, onClick, onChatClick, parentInsightTitle }: DeepInsightCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const actionInfo = actionConfig[insight.action];
  const ActionIcon = actionInfo.icon;

  // Get conversation count for this insight
  const { conversations } = useInsightConversations(insight.id);
  const conversationCount = conversations.length;
  const activeConversations = conversations.filter(c => c.status === 'ACTIVE').length;

  return (
    <Card
      className={cn(
        // Glassmorphism base
        'bg-card/80 backdrop-blur-sm border border-border/50',
        // Left accent border based on action type
        'border-l-4',
        actionInfo.borderColor,
        // Hover state
        'hover:shadow-xl hover:shadow-black/5 hover:scale-[1.01]',
        'transition-all duration-200 cursor-pointer',
        'overflow-hidden'
      )}
      onClick={onClick}
    >
      <CardHeader className="pb-3 pt-5 px-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            {/* Top row: Action badge + conversation badge */}
            <div className="flex flex-wrap items-center gap-2 mb-2.5">
              <Badge className={cn(actionInfo.color, 'shadow-sm font-semibold px-3 py-1')}>
                <ActionIcon className="w-3.5 h-3.5 mr-1.5" />
                {actionInfo.label}
              </Badge>

              {/* Primary symbol - prominent display */}
              {insight.primary_symbol && (
                <Badge
                  variant="outline"
                  className="text-sm font-bold cursor-pointer hover:bg-primary/10 px-3 py-1 border-2"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSymbolClick?.(insight.primary_symbol!);
                  }}
                >
                  {insight.primary_symbol}
                </Badge>
              )}

              {conversationCount > 0 && (
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Badge
                        variant="outline"
                        className="cursor-pointer hover:bg-primary/10 gap-1"
                        onClick={(e) => {
                          e.stopPropagation();
                          onChatClick?.(insight.id);
                        }}
                      >
                        <MessageSquare className="w-3 h-3" />
                        {conversationCount}
                        {activeConversations > 0 && activeConversations < conversationCount && (
                          <span className="text-green-600">({activeConversations} active)</span>
                        )}
                      </Badge>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{conversationCount} conversation{conversationCount !== 1 ? 's' : ''}</p>
                      {activeConversations > 0 && (
                        <p className="text-green-600">{activeConversations} active</p>
                      )}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              )}
            </div>

            {/* Parent insight indicator */}
            {parentInsightTitle && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mb-1.5">
                <GitBranch className="w-3 h-3 shrink-0" />
                <span className="truncate">Derived from: {parentInsightTitle}</span>
              </div>
            )}

            {/* Title */}
            <h3 className="text-lg font-semibold leading-tight tracking-tight mb-2">
              {insight.title}
            </h3>

            {/* Related symbols */}
            <div className="flex flex-wrap gap-1.5">
              {insight.related_symbols.slice(0, 4).map(symbol => (
                <Badge
                  key={symbol}
                  variant="secondary"
                  className="cursor-pointer hover:bg-secondary/80 text-xs"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSymbolClick?.(symbol);
                  }}
                >
                  {symbol}
                </Badge>
              ))}
              {insight.related_symbols.length > 4 && (
                <Badge variant="secondary" className="text-xs">
                  +{insight.related_symbols.length - 4}
                </Badge>
              )}
            </div>
          </div>

          {/* Right side: Confidence gauge, outcome, timestamp */}
          <div className="flex flex-col items-center gap-2 shrink-0">
            <ConfidenceGauge value={insight.confidence} />

            {/* Outcome Badge */}
            {(insight.action === 'BUY' || insight.action === 'STRONG_BUY' ||
              insight.action === 'SELL' || insight.action === 'STRONG_SELL') && (
              <TooltipProvider>
                <OutcomeBadge
                  insightId={insight.id}
                  size="sm"
                  showDetails={true}
                />
              </TooltipProvider>
            )}

            {insight.created_at && (
              <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
                <CalendarClock className="w-3 h-3" />
                <span>{formatInsightDate(insight.created_at)}</span>
              </div>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-5 pb-5">
        {/* Thesis */}
        <p className="text-sm text-muted-foreground leading-relaxed mb-4">{insight.thesis}</p>

        {/* Entry/Target/Stop Zone */}
        {insight.entry_zone && (
          <div className="grid grid-cols-3 gap-3 mb-4 p-3 rounded-lg bg-muted/40 border border-border/30">
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-muted-foreground mb-1">
                <DollarSign className="w-3 h-3" />
                <span className="text-[11px] uppercase tracking-wider font-medium">Entry</span>
              </div>
              <p className="font-semibold text-green-600 dark:text-green-400">{insight.entry_zone}</p>
            </div>
            <div className="text-center border-x border-border/30">
              <div className="flex items-center justify-center gap-1 text-muted-foreground mb-1">
                <ArrowUpRight className="w-3 h-3" />
                <span className="text-[11px] uppercase tracking-wider font-medium">Target</span>
              </div>
              <p className="font-semibold text-blue-600 dark:text-blue-400">{insight.target_price || '-'}</p>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-muted-foreground mb-1">
                <ArrowDownRight className="w-3 h-3" />
                <span className="text-[11px] uppercase tracking-wider font-medium">Stop</span>
              </div>
              <p className="font-semibold text-red-600 dark:text-red-400">{insight.stop_loss || '-'}</p>
            </div>
          </div>
        )}

        {/* Time horizon, type, and analyst badges row */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <Clock className="w-3.5 h-3.5" />
            <span>{insight.time_horizon}</span>
          </div>
          <Badge variant="outline" className="text-xs">{insight.insight_type}</Badge>
          {insight.timeframe && (
            <Badge variant="secondary" className="capitalize text-xs">{insight.timeframe}</Badge>
          )}

          {/* Analyst type badges */}
          {insight.analysts_involved.slice(0, 5).map((analyst) => {
            const config = getAnalystColorConfig(analyst);
            const AnalystIcon = config.icon;
            return (
              <Badge
                key={analyst}
                variant="outline"
                className={cn('text-xs gap-1 border', config.badge)}
              >
                <AnalystIcon className="w-3 h-3" />
                {formatAnalystName(analyst)}
              </Badge>
            );
          })}
        </div>

        {/* Expandable Details */}
        <Collapsible open={isExpanded} onOpenChange={setIsExpanded} onClick={(e: React.MouseEvent) => e.stopPropagation()}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full text-muted-foreground hover:text-foreground">
              {isExpanded ? (
                <>Less Details <ChevronUp className="ml-1 w-4 h-4" /></>
              ) : (
                <>More Details <ChevronDown className="ml-1 w-4 h-4" /></>
              )}
            </Button>
          </CollapsibleTrigger>

          <CollapsibleContent className="space-y-5 pt-4">
            {/* Supporting Evidence - redesigned analyst cards */}
            <div>
              <h4 className="text-sm font-semibold flex items-center gap-1.5 mb-3">
                <Users className="w-4 h-4" /> Analyst Evidence
              </h4>
              <div className="space-y-3">
                {insight.supporting_evidence.map((evidence, i) => {
                  const config = getAnalystColorConfig(evidence.analyst);
                  const AnalystIcon = config.icon;
                  const layman = getLaymanExplanation(evidence.analyst, evidence.finding);

                  return (
                    <div
                      key={i}
                      className={cn(
                        'rounded-lg border border-border/40 p-3 pl-4',
                        'border-l-[3px]',
                        config.border,
                        'bg-card/50'
                      )}
                    >
                      {/* Analyst header */}
                      <div className="flex items-center gap-2 mb-1.5">
                        <AnalystIcon className={cn('w-4 h-4 shrink-0', config.text)} />
                        <span className={cn('text-sm font-semibold', config.text)}>
                          {formatAnalystName(evidence.analyst)}
                        </span>
                        {evidence.confidence !== undefined && (
                          <span className="text-xs text-muted-foreground ml-auto">
                            {Math.round(evidence.confidence * 100)}%
                          </span>
                        )}
                      </div>

                      {/* Technical finding */}
                      <p className="text-sm leading-relaxed">{evidence.finding}</p>

                      {/* Layman explanation */}
                      <p className="text-xs text-muted-foreground italic mt-1.5 leading-relaxed">
                        {layman}
                      </p>

                      {/* Confidence bar */}
                      {evidence.confidence !== undefined && (
                        <ThinConfidenceBar value={evidence.confidence} colorClass={config.progress} />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Risk Factors */}
            {insight.risk_factors.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold flex items-center gap-1.5 mb-2">
                  <AlertTriangle className="w-4 h-4 text-yellow-500" /> Risk Factors
                </h4>
                <ul className="space-y-1.5">
                  {insight.risk_factors.map((risk, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <span className="text-yellow-500 mt-1 shrink-0">--</span>
                      <span>{risk}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Invalidation Trigger */}
            {insight.invalidation_trigger && (
              <div className="p-3 rounded-lg bg-rose-500/5 border border-rose-500/20">
                <h4 className="text-sm font-semibold flex items-center gap-1.5 mb-1.5">
                  <Shield className="w-4 h-4 text-rose-500" /> Invalidation Trigger
                </h4>
                <p className="text-sm text-muted-foreground">{insight.invalidation_trigger}</p>
              </div>
            )}

            {/* Historical Precedent */}
            {insight.historical_precedent && (
              <div className="p-3 rounded-lg bg-muted/40 border border-border/30">
                <h4 className="text-sm font-semibold flex items-center gap-1.5 mb-1.5">
                  <History className="w-4 h-4" /> Historical Precedent
                </h4>
                <p className="text-sm text-muted-foreground">{insight.historical_precedent}</p>
              </div>
            )}

            {/* Chat Button */}
            {onChatClick && (
              <div className="pt-2 border-t border-border/50">
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full gap-2"
                  onClick={(e) => {
                    e.stopPropagation();
                    onChatClick(insight.id);
                  }}
                >
                  <MessageSquare className="w-4 h-4" />
                  {conversationCount > 0 ? 'Continue Discussion' : 'Start Discussion'}
                </Button>
              </div>
            )}
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  );
}
