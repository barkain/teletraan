'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type SectorData,
  getPerformanceColor,
  getContrastTextColor,
  SECTOR_LIST,
} from '@/lib/hooks/use-sectors';

interface SectorHeatmapProps {
  sectors: SectorData[] | undefined;
  isLoading?: boolean;
  variant?: 'default' | 'compact' | 'mini';
  showVolume?: boolean;
  onSectorClick?: (sector: SectorData) => void;
  className?: string;
}

interface HeatmapCellProps {
  sector: SectorData;
  variant: 'default' | 'compact' | 'mini';
  showVolume?: boolean;
  onClick?: () => void;
}

function formatVolume(volume: number): string {
  if (volume >= 1000000000) {
    return `${(volume / 1000000000).toFixed(1)}B`;
  }
  if (volume >= 1000000) {
    return `${(volume / 1000000).toFixed(1)}M`;
  }
  if (volume >= 1000) {
    return `${(volume / 1000).toFixed(1)}K`;
  }
  return volume.toString();
}

function formatPerformance(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function HeatmapCell({ sector, variant, showVolume, onClick }: HeatmapCellProps) {
  const bgColor = getPerformanceColor(sector.performance);
  const textColor = getContrastTextColor(bgColor);

  const sizeClasses = {
    default: 'min-h-[100px] p-4',
    compact: 'min-h-[80px] p-3',
    mini: 'min-h-[60px] p-2',
  };

  const titleClasses = {
    default: 'text-sm font-semibold',
    compact: 'text-xs font-semibold',
    mini: 'text-[10px] font-medium',
  };

  const symbolClasses = {
    default: 'text-xs opacity-80',
    compact: 'text-[10px] opacity-80',
    mini: 'text-[9px] opacity-70',
  };

  const performanceClasses = {
    default: 'text-lg font-bold',
    compact: 'text-sm font-bold',
    mini: 'text-xs font-semibold',
  };

  return (
    <div
      className={cn(
        'relative flex flex-col justify-between rounded-lg transition-all duration-200 cursor-pointer',
        'hover:scale-[1.02] hover:shadow-lg hover:z-10',
        'border border-transparent hover:border-foreground/20',
        sizeClasses[variant]
      )}
      style={{
        backgroundColor: bgColor,
        color: textColor,
      }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          onClick?.();
        }
      }}
      aria-label={`${sector.name}: ${formatPerformance(sector.performance)}`}
    >
      {/* Tooltip on hover - only for default and compact variants */}
      {variant !== 'mini' && (
        <div className="absolute inset-0 opacity-0 hover:opacity-100 bg-black/80 rounded-lg p-3 flex flex-col justify-center items-center text-white transition-opacity z-20">
          <p className="font-semibold text-sm">{sector.name}</p>
          <p className="text-xs opacity-80 mb-2">{sector.symbol}</p>
          <div className="text-center space-y-1">
            <p className="text-sm">
              Daily: <span className="font-bold">{formatPerformance(sector.performance)}</span>
            </p>
            {sector.weeklyPerformance !== undefined && (
              <p className="text-xs opacity-80">
                Weekly: {formatPerformance(sector.weeklyPerformance)}
              </p>
            )}
            {sector.monthlyPerformance !== undefined && (
              <p className="text-xs opacity-80">
                Monthly: {formatPerformance(sector.monthlyPerformance)}
              </p>
            )}
            {showVolume && sector.volume && (
              <p className="text-xs opacity-80 mt-1">
                Vol: {formatVolume(sector.volume)}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-col gap-0.5">
        <p className={cn(titleClasses[variant], 'truncate')}>{sector.name}</p>
        <p className={symbolClasses[variant]}>{sector.symbol}</p>
      </div>

      <div className="flex items-end justify-between">
        <p className={performanceClasses[variant]}>
          {formatPerformance(sector.performance)}
        </p>
        {showVolume && variant === 'default' && sector.volume && (
          <p className="text-[10px] opacity-70">{formatVolume(sector.volume)}</p>
        )}
      </div>
    </div>
  );
}

function HeatmapSkeleton({ variant }: { variant: 'default' | 'compact' | 'mini' }) {
  const sizeClasses = {
    default: 'min-h-[100px]',
    compact: 'min-h-[80px]',
    mini: 'min-h-[60px]',
  };

  return (
    <div className={cn('rounded-lg', sizeClasses[variant])}>
      <Skeleton className="h-full w-full" />
    </div>
  );
}

export function SectorHeatmap({
  sectors,
  isLoading = false,
  variant = 'default',
  showVolume = false,
  onSectorClick,
  className,
}: SectorHeatmapProps) {
  // Merge API data with full sector list for consistent display
  const mergedSectors = React.useMemo(() => {
    if (!sectors) return [];

    return SECTOR_LIST.map((sectorInfo) => {
      const apiSector = sectors.find(
        (s) =>
          s.symbol === sectorInfo.symbol ||
          s.name.toLowerCase().includes(sectorInfo.name.toLowerCase().split(' ')[0])
      );
      return {
        symbol: sectorInfo.symbol,
        name: sectorInfo.name,
        performance: apiSector?.performance ?? 0,
        weeklyPerformance: apiSector?.weeklyPerformance ?? 0,
        monthlyPerformance: apiSector?.monthlyPerformance ?? 0,
        volume: apiSector?.volume ?? 0,
        marketCap: apiSector?.marketCap,
        price: apiSector?.price,
        change: apiSector?.change,
      };
    });
  }, [sectors]);

  // Sort by absolute performance for visual impact
  const sortedSectors = React.useMemo(() => {
    return [...mergedSectors].sort(
      (a, b) => Math.abs(b.performance) - Math.abs(a.performance)
    );
  }, [mergedSectors]);

  const gridClasses = {
    default: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3',
    compact: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2',
    mini: 'grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-1.5',
  };

  if (isLoading) {
    return (
      <div className={cn('grid', gridClasses[variant], className)}>
        {Array.from({ length: SECTOR_LIST.length }).map((_, i) => (
          <HeatmapSkeleton key={i} variant={variant} />
        ))}
      </div>
    );
  }

  return (
    <div className={cn('grid', gridClasses[variant], className)}>
      {sortedSectors.map((sector) => (
        <HeatmapCell
          key={sector.symbol}
          sector={sector}
          variant={variant}
          showVolume={showVolume}
          onClick={() => onSectorClick?.(sector)}
        />
      ))}
    </div>
  );
}

// Export a mini version for use in dashboard
export function SectorHeatmapMini({
  sectors,
  isLoading,
  onSectorClick,
  className,
}: Omit<SectorHeatmapProps, 'variant' | 'showVolume'>) {
  return (
    <SectorHeatmap
      sectors={sectors}
      isLoading={isLoading}
      variant="mini"
      onSectorClick={onSectorClick}
      className={className}
    />
  );
}
