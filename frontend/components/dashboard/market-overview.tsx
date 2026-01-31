'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import type { MarketIndex } from '@/lib/hooks/use-market-data';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

interface MarketOverviewProps {
  indices: MarketIndex[] | undefined;
  isLoading: boolean;
}

function getChangeColor(change: number): string {
  if (change > 0) return 'text-green-600 dark:text-green-500';
  if (change < 0) return 'text-red-600 dark:text-red-500';
  return 'text-muted-foreground';
}

function getChangeBgColor(change: number): string {
  if (change > 0) return 'bg-green-100 dark:bg-green-950 border-green-200 dark:border-green-800';
  if (change < 0) return 'bg-red-100 dark:bg-red-950 border-red-200 dark:border-red-800';
  return '';
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

function IndexCardSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-5 w-12" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-8 w-28 mb-2" />
        <Skeleton className="h-3 w-16" />
      </CardContent>
    </Card>
  );
}

function IndexCard({ index }: { index: MarketIndex }) {
  const changeColor = getChangeColor(index.change_percent);
  const bgColor = getChangeBgColor(index.change_percent);
  const formattedPrice = new Intl.NumberFormat('en-US', {
    style: 'decimal',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(index.price);

  const formattedChange = index.change >= 0
    ? `+${index.change.toFixed(2)}`
    : index.change.toFixed(2);

  const formattedPercent = index.change_percent >= 0
    ? `+${index.change_percent.toFixed(2)}%`
    : `${index.change_percent.toFixed(2)}%`;

  return (
    <Card className={cn('transition-colors', bgColor)}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{index.name}</CardTitle>
        <Badge variant="outline">{index.symbol}</Badge>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <div className="text-2xl font-bold">{formattedPrice}</div>
          <ChangeIndicator change={index.change_percent} />
        </div>
        <p className={cn('text-xs mt-1', changeColor)}>
          {formattedChange} ({formattedPercent})
        </p>
      </CardContent>
    </Card>
  );
}

export function MarketOverview({ indices, isLoading }: MarketOverviewProps) {
  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <IndexCardSkeleton />
        <IndexCardSkeleton />
        <IndexCardSkeleton />
      </div>
    );
  }

  if (!indices || indices.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-muted-foreground">
          No market data available
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {indices.map((index) => (
        <IndexCard key={index.symbol} index={index} />
      ))}
    </div>
  );
}
