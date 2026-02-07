'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import type { SectorPerformance } from '@/lib/hooks/use-market-data';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface SectorOverviewProps {
  sectors: SectorPerformance[] | undefined;
  isLoading: boolean;
}

// Full list of sectors with their display names
const SECTOR_NAMES = [
  { name: 'Technology', symbol: 'XLK' },
  { name: 'Healthcare', symbol: 'XLV' },
  { name: 'Financials', symbol: 'XLF' },
  { name: 'Energy', symbol: 'XLE' },
  { name: 'Consumer Discretionary', symbol: 'XLY' },
  { name: 'Industrials', symbol: 'XLI' },
  { name: 'Materials', symbol: 'XLB' },
  { name: 'Utilities', symbol: 'XLU' },
  { name: 'Real Estate', symbol: 'XLRE' },
  { name: 'Communication Services', symbol: 'XLC' },
];

function getPerformanceColor(changePercent: number): string {
  if (changePercent > 0) {
    return 'bg-green-100 dark:bg-green-950 border-green-200 dark:border-green-800';
  }
  if (changePercent < 0) {
    return 'bg-red-100 dark:bg-red-950 border-red-200 dark:border-red-800';
  }
  return '';
}

function getTextColor(changePercent: number): string {
  if (changePercent > 0) return 'text-green-600 dark:text-green-500';
  if (changePercent < 0) return 'text-red-600 dark:text-red-500';
  return 'text-muted-foreground';
}

function ChangeIndicator({ change }: { change: number }) {
  if (change > 0) {
    return <TrendingUp className="h-4 w-4 text-green-600 dark:text-green-500" />;
  }
  if (change < 0) {
    return <TrendingDown className="h-4 w-4 text-red-600 dark:text-red-500" />;
  }
  return <Minus className="h-4 w-4 text-muted-foreground" />;
}

function SectorCardSkeleton() {
  return (
    <Card className="p-3">
      <div className="flex items-center justify-between">
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-3 w-12" />
        </div>
        <Skeleton className="h-6 w-14" />
      </div>
    </Card>
  );
}

function SectorCard({
  name,
  symbol,
  changePercent
}: {
  name: string;
  symbol: string;
  changePercent: number;
}) {
  const bgColor = getPerformanceColor(changePercent);
  const textColor = getTextColor(changePercent);
  const formattedPercent = changePercent >= 0
    ? `+${changePercent.toFixed(2)}%`
    : `${changePercent.toFixed(2)}%`;

  return (
    <Card className={cn('p-3 transition-colors', bgColor)}>
      <div className="flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-sm truncate">{name}</p>
          <p className="text-xs text-muted-foreground">{symbol}</p>
        </div>
        <div className="flex items-center gap-1 ml-2">
          <ChangeIndicator change={changePercent} />
          <span className={cn('text-sm font-semibold', textColor)}>
            {formattedPercent}
          </span>
        </div>
      </div>
    </Card>
  );
}

export function SectorOverview({ sectors, isLoading }: SectorOverviewProps) {
  // Map API sectors to full sector list with fallback values
  const sectorData = SECTOR_NAMES.map((sector) => {
    const apiSector = sectors?.find(
      (s) => s.symbol === sector.symbol || s.name.toLowerCase().includes(sector.name.toLowerCase().split(' ')[0])
    );
    return {
      name: sector.name,
      symbol: sector.symbol,
      change_percent: apiSector?.change_percent ?? 0,
    };
  });

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Sector Performance</CardTitle>
        <CardDescription>
          Today&apos;s performance by market sector
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 10 }).map((_, i) => (
              <SectorCardSkeleton key={i} />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {sectorData.map((sector) => (
              <SectorCard
                key={sector.symbol}
                name={sector.name}
                symbol={sector.symbol}
                changePercent={sector.change_percent}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
