'use client';

import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  TrendingUp,
  TrendingDown,
  Globe,
  PieChart,
  Target,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type { DiscoveryContext } from '@/types';

interface DiscoveryContextCardProps {
  context: DiscoveryContext;
  className?: string;
}

const regimeColors: Record<string, string> = {
  'Risk-On': 'bg-green-500/10 text-green-500 border-green-500/20',
  'Risk-Off': 'bg-red-500/10 text-red-500 border-red-500/20',
  'Transitional': 'bg-yellow-500/10 text-yellow-500 border-yellow-500/20',
  'Range-Bound': 'bg-gray-500/10 text-gray-500 border-gray-500/20',
};

export function DiscoveryContextCard({ context, className }: DiscoveryContextCardProps) {
  const regimeColor = regimeColors[context.macro_regime] || 'bg-muted text-muted-foreground';

  return (
    <Card className={cn(className)}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Target className="h-4 w-4" />
          Discovery Context
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Market Regime */}
        <div>
          <span className="text-xs text-muted-foreground">Market Regime</span>
          <Badge
            variant="outline"
            className={cn('ml-2', regimeColor)}
          >
            {context.macro_regime === 'Risk-On' && <TrendingUp className="h-3 w-3 mr-1" />}
            {context.macro_regime === 'Risk-Off' && <TrendingDown className="h-3 w-3 mr-1" />}
            {context.macro_regime}
          </Badge>
        </div>

        {/* Macro Themes */}
        {context.macro_themes?.length > 0 && (
          <div>
            <span className="text-xs text-muted-foreground flex items-center gap-1 mb-1">
              <Globe className="h-3 w-3" />
              Key Themes
            </span>
            <div className="flex flex-wrap gap-1">
              {context.macro_themes.map((theme, i) => (
                <Badge key={i} variant="secondary" className="text-xs">
                  {theme}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Top Sectors */}
        {context.top_sectors?.length > 0 && (
          <div>
            <span className="text-xs text-muted-foreground flex items-center gap-1 mb-1">
              <PieChart className="h-3 w-3" />
              Focus Sectors
            </span>
            <div className="flex flex-wrap gap-1">
              {context.top_sectors.map((sector, i) => (
                <Badge key={i} variant="outline" className="text-xs text-blue-500 border-blue-500/20">
                  {sector}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Opportunity Type */}
        {context.opportunity_type && (
          <div>
            <span className="text-xs text-muted-foreground">Opportunity Type</span>
            <p className="text-sm font-medium capitalize">
              {context.opportunity_type.replace(/_/g, ' ')}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
