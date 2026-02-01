'use client';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Activity,
  TrendingUp,
  Building2
} from 'lucide-react';
import type { AutonomousAnalysisResponse } from '@/types';

interface AnalysisSummaryBannerProps {
  result: AutonomousAnalysisResponse;
}

export function AnalysisSummaryBanner({ result }: AnalysisSummaryBannerProps) {
  return (
    <Card className="p-4 bg-gradient-to-r from-blue-500/10 to-purple-500/10 border-blue-500/20">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-full bg-blue-500/20">
            <Activity className="h-5 w-5 text-blue-500" />
          </div>
          <div>
            <h3 className="font-semibold">Autonomous Analysis Complete</h3>
            <p className="text-sm text-muted-foreground">
              Discovered {result.insights_count} opportunities in {result.elapsed_seconds.toFixed(1)}s
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
            <span>Regime:</span>
            <Badge variant="outline">{result.market_regime}</Badge>
          </div>

          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-muted-foreground" />
            <span>Top Sectors:</span>
            {result.top_sectors.slice(0, 3).map((sector, i) => (
              <Badge key={i} variant="secondary" className="text-xs">
                {sector}
              </Badge>
            ))}
          </div>
        </div>
      </div>

      {/* Discovery Summary (expandable) */}
      {result.discovery_summary && (
        <details className="mt-3">
          <summary className="text-sm text-muted-foreground cursor-pointer hover:text-foreground">
            How were these opportunities found?
          </summary>
          <div className="mt-2 p-3 bg-background/50 rounded-lg text-sm whitespace-pre-line">
            {result.discovery_summary}
          </div>
        </details>
      )}
    </Card>
  );
}
