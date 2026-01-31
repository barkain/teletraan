'use client';

import { StockTable } from '@/components/stocks/stock-table';
import { useStocks } from '@/lib/hooks/use-stock';
import { RefreshDataButton } from '@/components/refresh-data-button';

export default function StocksPage() {
  const { data: stocks, isLoading } = useStocks();

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Stocks</h1>
          <p className="text-muted-foreground">
            Browse and track all stocks in your portfolio
          </p>
        </div>
        <RefreshDataButton />
      </div>

      {/* Stocks Table */}
      <div className="border rounded-lg">
        <StockTable stocks={stocks} isLoading={isLoading} />
      </div>
    </div>
  );
}
