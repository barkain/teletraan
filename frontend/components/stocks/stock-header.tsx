'use client';

import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import {
  formatCurrency,
  formatPercent,
  getChangeColorClass,
} from '@/lib/hooks/use-stock';
import type { Stock } from '@/types';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { ExportDialog } from '@/components/export';

interface StockHeaderProps {
  stock: Stock | undefined;
  isLoading: boolean;
  showExport?: boolean;
}

function ChangeIndicator({ change }: { change: number | undefined }) {
  if (change === undefined) return null;
  if (change > 0) {
    return <TrendingUp className="h-6 w-6 text-green-600 dark:text-green-500" />;
  }
  if (change < 0) {
    return <TrendingDown className="h-6 w-6 text-red-600 dark:text-red-500" />;
  }
  return <Minus className="h-6 w-6 text-muted-foreground" />;
}

function HeaderSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-10 w-24" />
          <Skeleton className="h-5 w-48" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-6 w-24" />
        </div>
      </div>
      <div className="flex items-baseline gap-3">
        <Skeleton className="h-12 w-32" />
        <Skeleton className="h-6 w-6" />
        <Skeleton className="h-6 w-20" />
      </div>
    </div>
  );
}

export function StockHeader({ stock, isLoading, showExport = true }: StockHeaderProps) {
  if (isLoading) {
    return <HeaderSkeleton />;
  }

  if (!stock) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        Stock not found
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-4xl font-bold tracking-tight">{stock.symbol}</h1>
          <p className="text-lg text-muted-foreground">{stock.name}</p>
        </div>
        <div className="flex gap-2 flex-wrap items-center">
          {stock.sector && (
            <Badge variant="secondary" className="text-sm">
              {stock.sector}
            </Badge>
          )}
          {showExport && (
            <ExportDialog type="analysis" symbol={stock.symbol} />
          )}
        </div>
      </div>

      <div className="flex items-baseline gap-3 flex-wrap">
        <span className="text-5xl font-bold">
          {formatCurrency(stock.current_price)}
        </span>
        <ChangeIndicator change={stock.change_percent} />
        <span
          className={cn(
            'text-xl font-semibold',
            getChangeColorClass(stock.change_percent)
          )}
        >
          {formatPercent(stock.change_percent)}
        </span>
      </div>

      {stock.updated_at && (
        <p className="text-sm text-muted-foreground">
          Last updated: {new Date(stock.updated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}
