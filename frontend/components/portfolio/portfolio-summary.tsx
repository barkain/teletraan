'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Portfolio } from '@/types';
import { DollarSign, TrendingUp, Wallet, BarChart3 } from 'lucide-react';

interface PortfolioSummaryProps {
  portfolio: Portfolio;
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});

const percentFormatter = new Intl.NumberFormat('en-US', {
  style: 'percent',
  minimumFractionDigits: 2,
});

function formatCurrency(value: number | undefined | null): string {
  if (value == null) return '\u2014';
  return currencyFormatter.format(value);
}

function formatPercent(value: number | undefined | null): string {
  if (value == null) return '\u2014';
  return percentFormatter.format(value / 100);
}

interface MetricTileProps {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}

function MetricTile({ title, icon, children }: MetricTileProps) {
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
        <div className="h-4 w-4">{icon}</div>
        {title}
      </div>
      <div>{children}</div>
    </div>
  );
}

export function PortfolioSummary({ portfolio }: PortfolioSummaryProps) {
  const gainLoss = portfolio.total_gain_loss;
  const gainLossPct = portfolio.total_gain_loss_pct;
  const isPositive = gainLoss != null && gainLoss >= 0;
  const plColorClass =
    gainLoss == null ? '' : isPositive ? 'text-green-500' : 'text-red-500';

  return (
    <Card>
      <CardHeader>
        <CardTitle>Portfolio Summary</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <MetricTile
            title="Total Value"
            icon={<DollarSign className="h-4 w-4" />}
          >
            <p className="text-2xl font-bold">
              {formatCurrency(portfolio.total_value)}
            </p>
          </MetricTile>

          <MetricTile
            title="Total Cost"
            icon={<Wallet className="h-4 w-4" />}
          >
            <p className="text-xl font-semibold">
              {formatCurrency(portfolio.total_cost)}
            </p>
          </MetricTile>

          <MetricTile
            title="Total P&L"
            icon={<TrendingUp className="h-4 w-4" />}
          >
            <p className={`text-xl font-semibold ${plColorClass}`}>
              {formatCurrency(gainLoss)}
            </p>
            <p className={`text-sm ${plColorClass}`}>
              {formatPercent(gainLossPct)}
            </p>
          </MetricTile>

          <MetricTile
            title="Holdings"
            icon={<BarChart3 className="h-4 w-4" />}
          >
            <p className="text-xl font-semibold">
              {portfolio.holdings?.length ?? 0}
            </p>
          </MetricTile>
        </div>
      </CardContent>
    </Card>
  );
}
