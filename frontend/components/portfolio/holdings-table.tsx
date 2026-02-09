'use client';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { Pencil, Trash2 } from 'lucide-react';
import type { PortfolioHolding } from '@/types';

interface HoldingsTableProps {
  holdings: PortfolioHolding[];
  onEdit: (holding: PortfolioHolding) => void;
  onDelete: (holdingId: number) => void;
}

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});

const numberFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 0,
  maximumFractionDigits: 4,
});

function formatCurrency(value: number | undefined | null): string {
  if (value == null) return '\u2014';
  return currencyFormatter.format(value);
}

function formatShares(value: number): string {
  return numberFormatter.format(value);
}

function formatPercent(value: number | undefined | null): string {
  if (value == null) return '\u2014';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function getGainLossColor(value: number | undefined | null): string {
  if (value == null) return 'text-muted-foreground';
  if (value > 0) return 'text-green-600 dark:text-green-500';
  if (value < 0) return 'text-red-600 dark:text-red-500';
  return 'text-muted-foreground';
}

export function HoldingsTable({ holdings, onEdit, onDelete }: HoldingsTableProps) {
  if (holdings.length === 0) {
    return (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right">Shares</TableHead>
            <TableHead className="text-right">Cost Basis</TableHead>
            <TableHead className="text-right">Current Price</TableHead>
            <TableHead className="text-right">Market Value</TableHead>
            <TableHead className="text-right">Gain/Loss</TableHead>
            <TableHead className="text-right">Allocation</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
              No holdings yet. Add a holding to get started.
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead className="text-right">Shares</TableHead>
          <TableHead className="text-right">Cost Basis</TableHead>
          <TableHead className="text-right">Current Price</TableHead>
          <TableHead className="text-right">Market Value</TableHead>
          <TableHead className="text-right">Gain/Loss</TableHead>
          <TableHead className="text-right">Allocation</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {holdings.map((holding) => (
          <TableRow key={holding.id}>
            <TableCell className="font-bold uppercase">
              {holding.symbol}
            </TableCell>
            <TableCell className="text-right">
              {formatShares(holding.shares)}
            </TableCell>
            <TableCell className="text-right">
              {formatCurrency(holding.cost_basis)}
            </TableCell>
            <TableCell className="text-right">
              {formatCurrency(holding.current_price)}
            </TableCell>
            <TableCell className="text-right font-medium">
              {formatCurrency(holding.market_value)}
            </TableCell>
            <TableCell className={cn('text-right font-medium', getGainLossColor(holding.gain_loss))}>
              <div className="flex flex-col items-end">
                <span>{formatCurrency(holding.gain_loss)}</span>
                <span className="text-xs">
                  {formatPercent(holding.gain_loss_pct)}
                </span>
              </div>
            </TableCell>
            <TableCell className="text-right">
              {holding.allocation_pct != null ? (
                <div className="flex items-center justify-end gap-2">
                  <div className="w-16 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full"
                      style={{ width: `${Math.min(holding.allocation_pct, 100)}%` }}
                    />
                  </div>
                  <Badge variant="secondary" className="min-w-[3.5rem] justify-center">
                    {holding.allocation_pct.toFixed(1)}%
                  </Badge>
                </div>
              ) : (
                <span className="text-muted-foreground">{'\u2014'}</span>
              )}
            </TableCell>
            <TableCell className="text-right">
              <div className="flex items-center justify-end gap-1">
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => onEdit(holding)}
                  aria-label={`Edit ${holding.symbol}`}
                >
                  <Pencil className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  onClick={() => onDelete(holding.id)}
                  aria-label={`Delete ${holding.symbol}`}
                  className="text-destructive hover:text-destructive"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
