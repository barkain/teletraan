'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import {
  formatCurrency,
  formatPercent,
  getChangeColorClass,
} from '@/lib/hooks/use-stock';
import type { Stock } from '@/types';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

interface StockTableProps {
  stocks: Stock[] | undefined;
  isLoading: boolean;
}

type SortField = 'symbol' | 'name' | 'sector' | 'current_price' | 'change_percent';
type SortDirection = 'asc' | 'desc';

function TableSkeleton() {
  return (
    <>
      {[...Array(5)].map((_, i) => (
        <TableRow key={i}>
          <TableCell><Skeleton className="h-4 w-16" /></TableCell>
          <TableCell><Skeleton className="h-4 w-32" /></TableCell>
          <TableCell><Skeleton className="h-5 w-20" /></TableCell>
          <TableCell><Skeleton className="h-4 w-20" /></TableCell>
          <TableCell><Skeleton className="h-4 w-16" /></TableCell>
        </TableRow>
      ))}
    </>
  );
}

function SortIcon({ field, sortField, sortDirection }: {
  field: SortField;
  sortField: SortField;
  sortDirection: SortDirection;
}) {
  if (field !== sortField) {
    return <ArrowUpDown className="ml-2 h-4 w-4" />;
  }
  return sortDirection === 'asc'
    ? <ArrowUp className="ml-2 h-4 w-4" />
    : <ArrowDown className="ml-2 h-4 w-4" />;
}

export function StockTable({ stocks, isLoading }: StockTableProps) {
  const [sortField, setSortField] = useState<SortField>('symbol');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const handleSort = (field: SortField) => {
    if (field === sortField) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const sortedStocks = useMemo(() => {
    if (!stocks) return [];

    return [...stocks].sort((a, b) => {
      let aValue: string | number | undefined;
      let bValue: string | number | undefined;

      switch (sortField) {
        case 'symbol':
          aValue = a.symbol;
          bValue = b.symbol;
          break;
        case 'name':
          aValue = a.name;
          bValue = b.name;
          break;
        case 'sector':
          aValue = a.sector || '';
          bValue = b.sector || '';
          break;
        case 'current_price':
          aValue = a.current_price || 0;
          bValue = b.current_price || 0;
          break;
        case 'change_percent':
          aValue = a.change_percent || 0;
          bValue = b.change_percent || 0;
          break;
      }

      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortDirection === 'asc'
          ? aValue.localeCompare(bValue)
          : bValue.localeCompare(aValue);
      }

      const numA = aValue as number;
      const numB = bValue as number;
      return sortDirection === 'asc' ? numA - numB : numB - numA;
    });
  }, [stocks, sortField, sortDirection]);

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead
            className="cursor-pointer hover:bg-muted/50"
            onClick={() => handleSort('symbol')}
          >
            <div className="flex items-center">
              Symbol
              <SortIcon field="symbol" sortField={sortField} sortDirection={sortDirection} />
            </div>
          </TableHead>
          <TableHead
            className="cursor-pointer hover:bg-muted/50"
            onClick={() => handleSort('name')}
          >
            <div className="flex items-center">
              Name
              <SortIcon field="name" sortField={sortField} sortDirection={sortDirection} />
            </div>
          </TableHead>
          <TableHead
            className="cursor-pointer hover:bg-muted/50"
            onClick={() => handleSort('sector')}
          >
            <div className="flex items-center">
              Sector
              <SortIcon field="sector" sortField={sortField} sortDirection={sortDirection} />
            </div>
          </TableHead>
          <TableHead
            className="cursor-pointer hover:bg-muted/50 text-right"
            onClick={() => handleSort('current_price')}
          >
            <div className="flex items-center justify-end">
              Price
              <SortIcon field="current_price" sortField={sortField} sortDirection={sortDirection} />
            </div>
          </TableHead>
          <TableHead
            className="cursor-pointer hover:bg-muted/50 text-right"
            onClick={() => handleSort('change_percent')}
          >
            <div className="flex items-center justify-end">
              Change %
              <SortIcon field="change_percent" sortField={sortField} sortDirection={sortDirection} />
            </div>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {isLoading ? (
          <TableSkeleton />
        ) : sortedStocks.length === 0 ? (
          <TableRow>
            <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
              No stocks found
            </TableCell>
          </TableRow>
        ) : (
          sortedStocks.map((stock) => (
            <TableRow key={stock.symbol} className="cursor-pointer hover:bg-muted/50">
              <TableCell>
                <Link
                  href={`/stocks/${stock.symbol}`}
                  className="font-medium text-primary hover:underline"
                >
                  {stock.symbol}
                </Link>
              </TableCell>
              <TableCell className="max-w-[200px] truncate">
                {stock.name}
              </TableCell>
              <TableCell>
                {stock.sector ? (
                  <Badge variant="secondary">{stock.sector}</Badge>
                ) : (
                  <span className="text-muted-foreground">-</span>
                )}
              </TableCell>
              <TableCell className="text-right font-medium">
                {formatCurrency(stock.current_price)}
              </TableCell>
              <TableCell className={cn('text-right font-medium', getChangeColorClass(stock.change_percent))}>
                {formatPercent(stock.change_percent)}
              </TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  );
}
