'use client';

import * as React from 'react';
import { ResponsiveContainer, Treemap, Tooltip } from 'recharts';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type SectorData,
  getPerformanceColor,
  getContrastTextColor,
  SECTOR_LIST,
  transformForTreemap,
} from '@/lib/hooks/use-sectors';

interface SectorTreemapProps {
  sectors: SectorData[] | undefined;
  isLoading?: boolean;
  height?: number;
  onSectorClick?: (sector: SectorData) => void;
  className?: string;
}

interface TreemapDataItem {
  name: string;
  symbol: string;
  size: number;
  color: number;
}

// Custom content renderer for treemap cells
interface CustomizedContentProps {
  root?: TreemapDataItem;
  depth?: number;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  index?: number;
  name?: string;
  symbol?: string;
  color?: number;
  onClick?: () => void;
}

function CustomizedContent({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  name,
  symbol,
  color = 0,
  onClick,
}: CustomizedContentProps) {
  const bgColor = getPerformanceColor(color);
  const textColor = getContrastTextColor(bgColor);

  // Only show text if cell is large enough
  const showName = width > 80 && height > 50;
  const showSymbol = width > 60 && height > 40;
  const showPerformance = width > 50 && height > 30;

  const formatPerformance = (value: number): string => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  return (
    <g
      className="cursor-pointer transition-opacity hover:opacity-90"
      onClick={onClick}
    >
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={4}
        ry={4}
        style={{
          fill: bgColor,
          stroke: 'rgba(255,255,255,0.3)',
          strokeWidth: 1,
        }}
      />
      {showName && (
        <text
          x={x + width / 2}
          y={y + height / 2 - (showSymbol ? 10 : 0)}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            fill: textColor,
            fontSize: width > 120 ? '12px' : '10px',
            fontWeight: 600,
          }}
        >
          {name}
        </text>
      )}
      {showSymbol && (
        <text
          x={x + width / 2}
          y={y + height / 2 + 5}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            fill: textColor,
            fontSize: '9px',
            opacity: 0.8,
          }}
        >
          {symbol}
        </text>
      )}
      {showPerformance && (
        <text
          x={x + width / 2}
          y={y + height / 2 + (showName ? 20 : 0)}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            fill: textColor,
            fontSize: width > 100 ? '11px' : '9px',
            fontWeight: 700,
          }}
        >
          {formatPerformance(color)}
        </text>
      )}
    </g>
  );
}

// Custom tooltip
interface TooltipPayload {
  payload?: {
    name?: string;
    symbol?: string;
    color?: number;
    size?: number;
  };
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayload[] }) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }

  const data = payload[0]?.payload;
  if (!data) return null;

  const formatPerformance = (value: number): string => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const formatMarketCap = (value: number): string => {
    if (value >= 1000000000000) {
      return `$${(value / 1000000000000).toFixed(2)}T`;
    }
    if (value >= 1000000000) {
      return `$${(value / 1000000000).toFixed(2)}B`;
    }
    return `$${(value / 1000000).toFixed(2)}M`;
  };

  return (
    <div className="bg-popover border border-border rounded-lg shadow-lg p-3 min-w-[150px]">
      <p className="font-semibold text-sm text-foreground">{data.name}</p>
      <p className="text-xs text-muted-foreground mb-2">{data.symbol}</p>
      <div className="space-y-1 text-sm">
        <p>
          Performance:{' '}
          <span
            className={cn(
              'font-bold',
              (data.color ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
            )}
          >
            {formatPerformance(data.color ?? 0)}
          </span>
        </p>
        {data.size && (
          <p className="text-muted-foreground">
            Market Cap: {formatMarketCap(data.size)}
          </p>
        )}
      </div>
    </div>
  );
}

function TreemapSkeleton({ height }: { height: number }) {
  return (
    <div className="w-full" style={{ height }}>
      <Skeleton className="h-full w-full rounded-lg" />
    </div>
  );
}

export function SectorTreemap({
  sectors,
  isLoading = false,
  height = 400,
  onSectorClick,
  className,
}: SectorTreemapProps) {
  // Transform data for treemap
  const treemapData = React.useMemo(() => {
    if (!sectors) return [];

    // Transform and add missing sectors
    const transformed = transformForTreemap(sectors);

    // Ensure all sectors are represented
    const existingSymbols = new Set(transformed.map((t) => t.symbol));
    SECTOR_LIST.forEach((sector) => {
      if (!existingSymbols.has(sector.symbol)) {
        transformed.push({
          name: sector.name,
          symbol: sector.symbol,
          size: 100000000000, // Default size for missing sectors
          color: 0,
        });
      }
    });

    return transformed;
  }, [sectors]);

  // Find sector by symbol for click handler
  const findSector = React.useCallback(
    (symbol: string): SectorData | undefined => {
      return sectors?.find((s) => s.symbol === symbol);
    },
    [sectors]
  );

  if (isLoading) {
    return <TreemapSkeleton height={height} />;
  }

  if (!treemapData.length) {
    return (
      <div
        className={cn(
          'flex items-center justify-center text-muted-foreground',
          className
        )}
        style={{ height }}
      >
        No sector data available
      </div>
    );
  }

  return (
    <div className={cn('w-full', className)} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <Treemap
          data={treemapData}
          dataKey="size"
          aspectRatio={4 / 3}
          stroke="transparent"
          content={
            <CustomizedContent
              onClick={() => {
                // This is handled per-cell below
              }}
            />
          }
        >
          {treemapData.map((entry) => (
            <CustomizedContent
              key={entry.symbol}
              name={entry.name}
              symbol={entry.symbol}
              color={entry.color}
              onClick={() => {
                const sector = findSector(entry.symbol);
                if (sector && onSectorClick) {
                  onSectorClick(sector);
                }
              }}
            />
          ))}
          <Tooltip content={<CustomTooltip />} />
        </Treemap>
      </ResponsiveContainer>
    </div>
  );
}

// Performance color legend component
export function SectorTreemapLegend({ className }: { className?: string }) {
  const gradientStops = [
    { value: -5, label: '-5%' },
    { value: -2.5, label: '-2.5%' },
    { value: 0, label: '0%' },
    { value: 2.5, label: '+2.5%' },
    { value: 5, label: '+5%' },
  ];

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <p className="text-xs text-muted-foreground">Performance</p>
      <div className="flex items-center gap-1">
        {gradientStops.map((stop, index) => (
          <div key={stop.value} className="flex flex-col items-center gap-1">
            <div
              className="w-8 h-4 rounded"
              style={{ backgroundColor: getPerformanceColor(stop.value) }}
            />
            {(index === 0 || index === gradientStops.length - 1 || index === 2) && (
              <span className="text-[10px] text-muted-foreground">{stop.label}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
