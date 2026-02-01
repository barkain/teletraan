'use client';

import { useQuery } from '@tanstack/react-query';
import { fetchApi } from '@/lib/api';
import { toast } from 'sonner';
import { useEffect } from 'react';

// Enhanced sector data interface
export interface SectorData {
  symbol: string;           // ETF symbol (XLK, XLV, etc.)
  name: string;             // "Technology", "Healthcare", etc.
  performance: number;      // Daily change %
  weeklyPerformance: number;
  monthlyPerformance: number;
  volume: number;
  marketCap?: number;
  price?: number;
  change?: number;
}

// Sector rotation phase
export type SectorRotationPhase =
  | 'early_expansion'    // Technology, Consumer Discretionary lead
  | 'mid_expansion'      // Industrials, Materials lead
  | 'late_expansion'     // Energy, Materials lead
  | 'early_contraction'  // Utilities, Healthcare lead
  | 'late_contraction'   // Consumer Staples, Healthcare lead
  | 'recovery';          // Financials, Technology lead

// Historical sector performance for charts
export interface SectorHistoricalData {
  date: string;
  [sectorSymbol: string]: number | string;
}

// Sector details response
export interface SectorDetailsResponse {
  sectors: SectorData[];
  rotationPhase: SectorRotationPhase;
  historicalPerformance: SectorHistoricalData[];
  lastUpdated: string;
}

// Full list of S&P 500 sectors
export const SECTOR_LIST: Array<{ symbol: string; name: string; color: string }> = [
  { symbol: 'XLK', name: 'Technology', color: '#3B82F6' },
  { symbol: 'XLV', name: 'Healthcare', color: '#10B981' },
  { symbol: 'XLF', name: 'Financials', color: '#8B5CF6' },
  { symbol: 'XLE', name: 'Energy', color: '#F59E0B' },
  { symbol: 'XLY', name: 'Consumer Discretionary', color: '#EC4899' },
  { symbol: 'XLI', name: 'Industrials', color: '#6366F1' },
  { symbol: 'XLB', name: 'Materials', color: '#14B8A6' },
  { symbol: 'XLU', name: 'Utilities', color: '#84CC16' },
  { symbol: 'XLRE', name: 'Real Estate', color: '#F97316' },
  { symbol: 'XLC', name: 'Communication Services', color: '#06B6D4' },
  { symbol: 'XLP', name: 'Consumer Staples', color: '#A855F7' },
];

const REFRESH_INTERVAL = 60 * 1000; // 60 seconds

function determineSectorRotationPhase(sectors: SectorData[]): SectorRotationPhase {
  // Simple heuristic based on sector leadership
  const sortedByPerformance = [...sectors].sort((a, b) => b.performance - a.performance);
  const topSectors = sortedByPerformance.slice(0, 3).map(s => s.symbol);

  if (topSectors.includes('XLK') && topSectors.includes('XLY')) {
    return 'early_expansion';
  }
  if (topSectors.includes('XLI') && topSectors.includes('XLB')) {
    return 'mid_expansion';
  }
  if (topSectors.includes('XLE') && topSectors.includes('XLB')) {
    return 'late_expansion';
  }
  if (topSectors.includes('XLU') && topSectors.includes('XLV')) {
    return 'early_contraction';
  }
  if (topSectors.includes('XLP') && topSectors.includes('XLV')) {
    return 'late_contraction';
  }
  return 'recovery';
}

/**
 * Custom hook for fetching sector performance data
 * Auto-refreshes every 60 seconds
 */
export function useSectors() {
  const query = useQuery<SectorDetailsResponse>({
    queryKey: ['sectors-detailed'],
    queryFn: () => fetchApi<SectorDetailsResponse>('/api/market/sectors'),
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  });

  useEffect(() => {
    if (query.error) {
      toast.error('Failed to fetch sector data', {
        description: 'Unable to load sector performance data.',
      });
    }
  }, [query.error]);

  return {
    ...query,
    isEmpty: !query.isLoading && !query.isError && (!query.data?.sectors || query.data.sectors.length === 0),
  };
}

/**
 * Transform sector data for heatmap visualization
 */
export function transformForHeatmap(sectors: SectorData[] | undefined): SectorData[] {
  if (!sectors) return [];

  return sectors.map((sector) => {
    // Find sector info from SECTOR_LIST for consistent naming
    const sectorInfo = SECTOR_LIST.find(s => s.symbol === sector.symbol);
    return {
      ...sector,
      name: sectorInfo?.name || sector.name,
    };
  });
}

/**
 * Transform sector data for treemap visualization
 */
export function transformForTreemap(sectors: SectorData[] | undefined): Array<{
  name: string;
  symbol: string;
  size: number;
  color: number;
}> {
  if (!sectors) return [];

  return sectors.map((sector) => {
    const sectorInfo = SECTOR_LIST.find(s => s.symbol === sector.symbol);
    return {
      name: sectorInfo?.name || sector.name,
      symbol: sector.symbol,
      size: sector.marketCap || sector.volume || 1000000000,
      color: sector.performance,
    };
  });
}

/**
 * Get color for performance value
 * Deep red (-5%+) -> light red -> white (0%) -> light green -> deep green (+5%+)
 */
export function getPerformanceColor(value: number): string {
  // Clamp value between -5 and 5
  const clamped = Math.max(-5, Math.min(5, value));

  if (clamped === 0) {
    return '#FFFFFF';
  }

  if (clamped > 0) {
    // Green gradient
    const intensity = Math.min(clamped / 5, 1);
    const r = Math.round(255 - (255 - 34) * intensity);
    const g = Math.round(255 - (255 - 197) * intensity);
    const b = Math.round(255 - (255 - 94) * intensity);
    return `rgb(${r}, ${g}, ${b})`;
  } else {
    // Red gradient
    const intensity = Math.min(Math.abs(clamped) / 5, 1);
    const r = Math.round(255 - (255 - 239) * intensity);
    const g = Math.round(255 - (255 - 68) * intensity);
    const b = Math.round(255 - (255 - 68) * intensity);
    return `rgb(${r}, ${g}, ${b})`;
  }
}

/**
 * Get text color that contrasts with background
 */
export function getContrastTextColor(bgColor: string): string {
  // Parse RGB from color string
  const match = bgColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!match) return '#000000';

  const [, r, g, b] = match.map(Number);
  // Calculate luminance
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;

  return luminance > 0.5 ? '#000000' : '#FFFFFF';
}

/**
 * Format rotation phase for display
 */
export function formatRotationPhase(phase: SectorRotationPhase): string {
  const phaseLabels: Record<SectorRotationPhase, string> = {
    early_expansion: 'Early Expansion',
    mid_expansion: 'Mid Expansion',
    late_expansion: 'Late Expansion',
    early_contraction: 'Early Contraction',
    late_contraction: 'Late Contraction',
    recovery: 'Recovery',
  };
  return phaseLabels[phase] || phase;
}

/**
 * Get rotation phase description
 */
export function getRotationPhaseDescription(phase: SectorRotationPhase): string {
  const descriptions: Record<SectorRotationPhase, string> = {
    early_expansion: 'Economic growth accelerating. Technology and Consumer Discretionary typically lead.',
    mid_expansion: 'Growth continuing. Industrials and Materials benefit from increased activity.',
    late_expansion: 'Growth peaking. Energy and Materials often outperform as inflation rises.',
    early_contraction: 'Growth slowing. Defensive sectors like Utilities and Healthcare favored.',
    late_contraction: 'Economic decline. Consumer Staples and Healthcare provide stability.',
    recovery: 'Economy bottoming. Financials and Technology often lead the recovery.',
  };
  return descriptions[phase] || '';
}
