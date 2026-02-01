'use client';

import { useState } from 'react';
import {
  TrendingUp, TrendingDown, Minus, AlertTriangle, Clock,
  ChevronDown, ChevronUp, Target, Shield, History, Users, CalendarClock,
  DollarSign, ArrowUpRight, ArrowDownRight, MessageSquare, GitBranch
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { TooltipProvider, Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { DeepInsight, InsightAction } from '@/types';
import { OutcomeBadge } from './outcome-badge';
import { useInsightConversations } from '@/lib/hooks/use-insight-conversation';

interface DeepInsightCardProps {
  insight: DeepInsight;
  onSymbolClick?: (symbol: string) => void;
  onClick?: () => void;
  onChatClick?: (insightId: number) => void;
  parentInsightTitle?: string;
}

const actionConfig: Record<InsightAction, { color: string; icon: typeof TrendingUp; label: string }> = {
  STRONG_BUY: { color: 'bg-green-600', icon: TrendingUp, label: 'Strong Buy' },
  BUY: { color: 'bg-green-500', icon: TrendingUp, label: 'Buy' },
  HOLD: { color: 'bg-yellow-500', icon: Minus, label: 'Hold' },
  SELL: { color: 'bg-red-500', icon: TrendingDown, label: 'Sell' },
  STRONG_SELL: { color: 'bg-red-600', icon: TrendingDown, label: 'Strong Sell' },
  WATCH: { color: 'bg-blue-500', icon: Target, label: 'Watch' },
};

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

export function DeepInsightCard({ insight, onSymbolClick, onClick, onChatClick, parentInsightTitle }: DeepInsightCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const actionInfo = actionConfig[insight.action];
  const ActionIcon = actionInfo.icon;

  // Get conversation count for this insight
  const { conversations } = useInsightConversations(insight.id);
  const conversationCount = conversations.length;
  const activeConversations = conversations.filter(c => c.status === 'ACTIVE').length;

  return (
    <Card className="hover:shadow-lg transition-shadow cursor-pointer" onClick={onClick}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            {/* Action Badge and Conversation Badge */}
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <Badge className={`${actionInfo.color} text-white`}>
                <ActionIcon className="w-3 h-3 mr-1" />
                {actionInfo.label}
              </Badge>
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

            {/* Parent Insight Indicator */}
            {parentInsightTitle && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
                <GitBranch className="w-3 h-3" />
                <span>Derived from: {parentInsightTitle}</span>
              </div>
            )}

            <CardTitle className="text-lg">{insight.title}</CardTitle>

            {/* Symbols */}
            <div className="flex flex-wrap gap-1 mt-2">
              {insight.primary_symbol && (
                <Badge
                  variant="outline"
                  className="cursor-pointer hover:bg-primary/10"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSymbolClick?.(insight.primary_symbol!);
                  }}
                >
                  {insight.primary_symbol}
                </Badge>
              )}
              {insight.related_symbols.slice(0, 3).map(symbol => (
                <Badge
                  key={symbol}
                  variant="secondary"
                  className="cursor-pointer hover:bg-secondary/80"
                  onClick={(e) => {
                    e.stopPropagation();
                    onSymbolClick?.(symbol);
                  }}
                >
                  {symbol}
                </Badge>
              ))}
              {insight.related_symbols.length > 3 && (
                <Badge variant="secondary">+{insight.related_symbols.length - 3}</Badge>
              )}
            </div>
          </div>

          {/* Confidence Score, Outcome & Timestamp */}
          <div className="text-right flex flex-col items-end gap-2">
            <div>
              <div className="text-2xl font-bold">{Math.round(insight.confidence * 100)}%</div>
              <div className="text-xs text-muted-foreground">confidence</div>
            </div>
            {/* Outcome Badge - shows tracking status/result for actionable insights */}
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
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1">
                <CalendarClock className="w-3.5 h-3.5" />
                <span className="font-medium">{formatInsightDate(insight.created_at)}</span>
              </div>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Thesis */}
        <p className="text-sm text-muted-foreground mb-4">{insight.thesis}</p>

        {/* Entry/Target/Stop Zone - Autonomous Discovery */}
        {insight.entry_zone && (
          <div className="grid grid-cols-3 gap-2 mb-4 p-3 bg-muted/50 rounded-lg text-sm">
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-muted-foreground mb-1">
                <DollarSign className="w-3 h-3" />
                <span className="text-xs">Entry</span>
              </div>
              <p className="font-semibold text-green-600 dark:text-green-400">{insight.entry_zone}</p>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-muted-foreground mb-1">
                <ArrowUpRight className="w-3 h-3" />
                <span className="text-xs">Target</span>
              </div>
              <p className="font-semibold text-blue-600 dark:text-blue-400">{insight.target_price || '-'}</p>
            </div>
            <div className="text-center">
              <div className="flex items-center justify-center gap-1 text-muted-foreground mb-1">
                <ArrowDownRight className="w-3 h-3" />
                <span className="text-xs">Stop</span>
              </div>
              <p className="font-semibold text-red-600 dark:text-red-400">{insight.stop_loss || '-'}</p>
            </div>
          </div>
        )}

        {/* Time Horizon & Type */}
        <div className="flex flex-wrap gap-2 mb-4 text-sm">
          <div className="flex items-center gap-1">
            <Clock className="w-4 h-4 text-muted-foreground" />
            <span>{insight.time_horizon}</span>
          </div>
          <Badge variant="outline">{insight.insight_type}</Badge>
          {insight.timeframe && (
            <Badge variant="secondary" className="capitalize">{insight.timeframe}</Badge>
          )}
        </div>

        {/* Expandable Details */}
        <Collapsible open={isExpanded} onOpenChange={setIsExpanded} onClick={(e: React.MouseEvent) => e.stopPropagation()}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full">
              {isExpanded ? (
                <>Less Details <ChevronUp className="ml-1 w-4 h-4" /></>
              ) : (
                <>More Details <ChevronDown className="ml-1 w-4 h-4" /></>
              )}
            </Button>
          </CollapsibleTrigger>

          <CollapsibleContent className="space-y-4 pt-4">
            {/* Supporting Evidence */}
            <div>
              <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                <Users className="w-4 h-4" /> Analyst Evidence
              </h4>
              <div className="space-y-2">
                {insight.supporting_evidence.map((evidence, i) => (
                  <div key={i} className="text-sm pl-4 border-l-2 border-muted">
                    <span className="font-medium capitalize">{evidence.analyst}:</span>{' '}
                    <span className="text-muted-foreground">{evidence.finding}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Risk Factors */}
            {insight.risk_factors.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                  <AlertTriangle className="w-4 h-4 text-yellow-500" /> Risk Factors
                </h4>
                <ul className="text-sm text-muted-foreground list-disc list-inside">
                  {insight.risk_factors.map((risk, i) => (
                    <li key={i}>{risk}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Invalidation Trigger */}
            {insight.invalidation_trigger && (
              <div>
                <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                  <Shield className="w-4 h-4 text-red-500" /> Invalidation Trigger
                </h4>
                <p className="text-sm text-muted-foreground">{insight.invalidation_trigger}</p>
              </div>
            )}

            {/* Historical Precedent */}
            {insight.historical_precedent && (
              <div>
                <h4 className="text-sm font-semibold flex items-center gap-1 mb-2">
                  <History className="w-4 h-4" /> Historical Precedent
                </h4>
                <p className="text-sm text-muted-foreground">{insight.historical_precedent}</p>
              </div>
            )}

            {/* Chat Button */}
            {onChatClick && (
              <div className="pt-2 border-t">
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
