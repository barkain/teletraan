'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { TrendingUp, TrendingDown, Activity } from 'lucide-react';
import type { PortfolioImpact as PortfolioImpactType } from '@/types';

interface PortfolioImpactProps {
  impact: PortfolioImpactType | undefined;
  isLoading: boolean;
}

function getDirectionConfig(direction: string) {
  switch (direction) {
    case 'bullish':
      return {
        icon: <TrendingUp className="h-3 w-3" />,
        className: 'bg-green-500/10 text-green-700 border-green-500/20',
        label: 'Bullish',
      };
    case 'bearish':
      return {
        icon: <TrendingDown className="h-3 w-3" />,
        className: 'bg-red-500/10 text-red-700 border-red-500/20',
        label: 'Bearish',
      };
    default:
      return {
        icon: <Activity className="h-3 w-3" />,
        className: 'bg-yellow-500/10 text-yellow-700 border-yellow-500/20',
        label: 'Neutral',
      };
  }
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-2 w-full" />
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-2 w-full" />
      </div>
      <Skeleton className="h-4 w-48" />
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </div>
  );
}

export function PortfolioImpact({ impact, isLoading }: PortfolioImpactProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Insight Impact Analysis</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingSkeleton />
        ) : !impact || impact.affected_holdings.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            No active insights affect your portfolio
          </div>
        ) : (
          <div className="space-y-4">
            {/* Overall Exposure */}
            <div className="space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-green-700">
                    <TrendingUp className="h-3 w-3" />
                    Bullish Exposure
                  </span>
                  <span className="font-medium">
                    {Math.round(impact.overall_bullish_exposure)}%
                  </span>
                </div>
                <div className="h-2 w-full bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-green-500 transition-all"
                    style={{ width: `${Math.min(impact.overall_bullish_exposure, 100)}%` }}
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-red-700">
                    <TrendingDown className="h-3 w-3" />
                    Bearish Exposure
                  </span>
                  <span className="font-medium">
                    {Math.round(impact.overall_bearish_exposure)}%
                  </span>
                </div>
                <div className="h-2 w-full bg-secondary rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-red-500 transition-all"
                    style={{ width: `${Math.min(impact.overall_bearish_exposure, 100)}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Insight Count */}
            <p className="text-xs text-muted-foreground">
              Based on {impact.insight_count} active insight{impact.insight_count !== 1 ? 's' : ''}
            </p>

            {/* Affected Holdings */}
            <div className="space-y-2">
              {impact.affected_holdings.map((holding) => {
                const dirConfig = getDirectionConfig(holding.impact_direction);
                return (
                  <div
                    key={holding.symbol}
                    className="flex items-center justify-between rounded-md border p-2.5"
                  >
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary" className="font-mono">
                        {holding.symbol}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {holding.allocation_pct.toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={cn('gap-1 text-xs', dirConfig.className)}
                      >
                        {dirConfig.icon}
                        {dirConfig.label}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {holding.insight_ids.length} insight{holding.insight_ids.length !== 1 ? 's' : ''}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
