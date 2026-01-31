'use client';

import { useState } from 'react';
import {
  TrendingUp, TrendingDown, Minus, AlertTriangle, Clock,
  ChevronDown, ChevronUp, Target, Shield, History, Users
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { DeepInsight, InsightAction } from '@/types';

interface DeepInsightCardProps {
  insight: DeepInsight;
  onSymbolClick?: (symbol: string) => void;
}

const actionConfig: Record<InsightAction, { color: string; icon: typeof TrendingUp; label: string }> = {
  STRONG_BUY: { color: 'bg-green-600', icon: TrendingUp, label: 'Strong Buy' },
  BUY: { color: 'bg-green-500', icon: TrendingUp, label: 'Buy' },
  HOLD: { color: 'bg-yellow-500', icon: Minus, label: 'Hold' },
  SELL: { color: 'bg-red-500', icon: TrendingDown, label: 'Sell' },
  STRONG_SELL: { color: 'bg-red-600', icon: TrendingDown, label: 'Strong Sell' },
  WATCH: { color: 'bg-blue-500', icon: Target, label: 'Watch' },
};

export function DeepInsightCard({ insight, onSymbolClick }: DeepInsightCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const actionInfo = actionConfig[insight.action];
  const ActionIcon = actionInfo.icon;

  return (
    <Card className="hover:shadow-lg transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            {/* Action Badge */}
            <Badge className={`${actionInfo.color} text-white mb-2`}>
              <ActionIcon className="w-3 h-3 mr-1" />
              {actionInfo.label}
            </Badge>

            <CardTitle className="text-lg">{insight.title}</CardTitle>

            {/* Symbols */}
            <div className="flex flex-wrap gap-1 mt-2">
              {insight.primary_symbol && (
                <Badge
                  variant="outline"
                  className="cursor-pointer hover:bg-primary/10"
                  onClick={() => onSymbolClick?.(insight.primary_symbol!)}
                >
                  {insight.primary_symbol}
                </Badge>
              )}
              {insight.related_symbols.slice(0, 3).map(symbol => (
                <Badge
                  key={symbol}
                  variant="secondary"
                  className="cursor-pointer hover:bg-secondary/80"
                  onClick={() => onSymbolClick?.(symbol)}
                >
                  {symbol}
                </Badge>
              ))}
              {insight.related_symbols.length > 3 && (
                <Badge variant="secondary">+{insight.related_symbols.length - 3}</Badge>
              )}
            </div>
          </div>

          {/* Confidence Score */}
          <div className="text-right">
            <div className="text-2xl font-bold">{Math.round(insight.confidence * 100)}%</div>
            <div className="text-xs text-muted-foreground">confidence</div>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {/* Thesis */}
        <p className="text-sm text-muted-foreground mb-4">{insight.thesis}</p>

        {/* Time Horizon & Type */}
        <div className="flex gap-4 mb-4 text-sm">
          <div className="flex items-center gap-1">
            <Clock className="w-4 h-4 text-muted-foreground" />
            <span>{insight.time_horizon}</span>
          </div>
          <Badge variant="outline">{insight.insight_type}</Badge>
        </div>

        {/* Expandable Details */}
        <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
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
          </CollapsibleContent>
        </Collapsible>
      </CardContent>
    </Card>
  );
}
