'use client';

import * as React from 'react';
import Link from 'next/link';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
import { SectorHeatmap } from '@/components/charts/sector-heatmap';
import { SectorTreemap, SectorTreemapLegend } from '@/components/charts/sector-treemap';
import {
  useSectors,
  formatRotationPhase,
  getRotationPhaseDescription,
  type SectorData,
  type SectorRotationPhase,
  SECTOR_LIST,
} from '@/lib/hooks/use-sectors';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts';
import { cn } from '@/lib/utils';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  ArrowLeft,
  RefreshCw,
  BarChart3,
  Grid3X3,
  ChevronRight,
} from 'lucide-react';
import { Button } from '@/components/ui/button';

// Sector rotation phase indicator component
function RotationPhaseIndicator({
  phase,
  isLoading,
}: {
  phase: SectorRotationPhase | undefined;
  isLoading: boolean;
}) {
  if (isLoading || !phase) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-60" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-8 w-32" />
        </CardContent>
      </Card>
    );
  }

  const phaseColors: Record<SectorRotationPhase, string> = {
    early_expansion: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-100',
    mid_expansion: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100',
    late_expansion: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-100',
    early_contraction: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-100',
    late_contraction: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-100',
    recovery: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-100',
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Sector Rotation Phase</CardTitle>
        <CardDescription>
          Current market cycle position based on sector leadership
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Badge className={cn('text-sm px-3 py-1', phaseColors[phase])}>
          {formatRotationPhase(phase)}
        </Badge>
        <p className="text-sm text-muted-foreground">
          {getRotationPhaseDescription(phase)}
        </p>
      </CardContent>
    </Card>
  );
}

// Historical performance chart
function HistoricalPerformanceChart({
  data,
  isLoading,
}: {
  data: Array<{ date: string; [key: string]: number | string }> | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-4 w-64" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[300px] w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Historical Performance</CardTitle>
          <CardDescription>30-day sector performance comparison</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-center h-[300px] text-muted-foreground">
          No historical data available
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Historical Performance</CardTitle>
        <CardDescription>30-day sector performance comparison</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10 }}
                tickFormatter={(value) => {
                  const date = new Date(value);
                  return `${date.getMonth() + 1}/${date.getDate()}`;
                }}
              />
              <YAxis
                tick={{ fontSize: 10 }}
                tickFormatter={(value) => `${value.toFixed(1)}%`}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload) return null;
                  return (
                    <div className="bg-popover border border-border rounded-lg shadow-lg p-3">
                      <p className="font-semibold text-sm mb-2">{label}</p>
                      <div className="space-y-1">
                        {payload.slice(0, 5).map((entry) => (
                          <p
                            key={entry.dataKey as string}
                            className="text-xs flex items-center gap-2"
                          >
                            <span
                              className="w-2 h-2 rounded-full"
                              style={{ backgroundColor: entry.color }}
                            />
                            <span>{entry.dataKey}:</span>
                            <span className="font-medium">
                              {(entry.value as number).toFixed(2)}%
                            </span>
                          </p>
                        ))}
                      </div>
                    </div>
                  );
                }}
              />
              <Legend
                verticalAlign="bottom"
                height={36}
                formatter={(value) => (
                  <span className="text-xs text-muted-foreground">{value}</span>
                )}
              />
              {SECTOR_LIST.slice(0, 6).map((sector) => (
                <Line
                  key={sector.symbol}
                  type="monotone"
                  dataKey={sector.symbol}
                  stroke={sector.color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

// Sector rankings table
function SectorRankingsTable({
  sectors,
  isLoading,
}: {
  sectors: SectorData[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-48" />
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {Array.from({ length: 11 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!sectors || sectors.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Sector Rankings</CardTitle>
          <CardDescription>Ranked by daily performance</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-center h-[200px] text-muted-foreground">
          No sector data available
        </CardContent>
      </Card>
    );
  }

  // Merge with SECTOR_LIST and sort by performance
  const sortedSectors = SECTOR_LIST.map((sectorInfo) => {
    const apiSector = sectors.find((s) => s.symbol === sectorInfo.symbol);
    return {
      ...sectorInfo,
      performance: apiSector?.performance ?? 0,
      weeklyPerformance: apiSector?.weeklyPerformance ?? 0,
      monthlyPerformance: apiSector?.monthlyPerformance ?? 0,
      volume: apiSector?.volume ?? 0,
    };
  }).sort((a, b) => b.performance - a.performance);

  const formatPerformance = (value: number) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const formatVolume = (value: number) => {
    if (value >= 1000000000) return `${(value / 1000000000).toFixed(1)}B`;
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    return value.toString();
  };

  const ChangeIcon = ({ value }: { value: number }) => {
    if (value > 0) return <TrendingUp className="h-4 w-4 text-green-600" />;
    if (value < 0) return <TrendingDown className="h-4 w-4 text-red-600" />;
    return <Minus className="h-4 w-4 text-muted-foreground" />;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Sector Rankings</CardTitle>
        <CardDescription>Ranked by daily performance</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-12">#</TableHead>
              <TableHead>Sector</TableHead>
              <TableHead className="text-right">Daily</TableHead>
              <TableHead className="text-right hidden sm:table-cell">Weekly</TableHead>
              <TableHead className="text-right hidden md:table-cell">Monthly</TableHead>
              <TableHead className="text-right hidden lg:table-cell">Volume</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedSectors.map((sector, index) => (
              <TableRow key={sector.symbol} className="cursor-pointer hover:bg-muted/50">
                <TableCell className="font-medium">{index + 1}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: sector.color }}
                    />
                    <div>
                      <p className="font-medium text-sm">{sector.name}</p>
                      <p className="text-xs text-muted-foreground">{sector.symbol}</p>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center justify-end gap-1">
                    <ChangeIcon value={sector.performance} />
                    <span
                      className={cn(
                        'font-medium',
                        sector.performance > 0
                          ? 'text-green-600'
                          : sector.performance < 0
                          ? 'text-red-600'
                          : 'text-muted-foreground'
                      )}
                    >
                      {formatPerformance(sector.performance)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="text-right hidden sm:table-cell">
                  <span
                    className={cn(
                      'text-sm',
                      sector.weeklyPerformance > 0
                        ? 'text-green-600'
                        : sector.weeklyPerformance < 0
                        ? 'text-red-600'
                        : 'text-muted-foreground'
                    )}
                  >
                    {formatPerformance(sector.weeklyPerformance)}
                  </span>
                </TableCell>
                <TableCell className="text-right hidden md:table-cell">
                  <span
                    className={cn(
                      'text-sm',
                      sector.monthlyPerformance > 0
                        ? 'text-green-600'
                        : sector.monthlyPerformance < 0
                        ? 'text-red-600'
                        : 'text-muted-foreground'
                    )}
                  >
                    {formatPerformance(sector.monthlyPerformance)}
                  </span>
                </TableCell>
                <TableCell className="text-right hidden lg:table-cell text-muted-foreground text-sm">
                  {formatVolume(sector.volume)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export default function SectorsPage() {
  const { data, isLoading, refetch, isFetching } = useSectors();
  const [selectedView, setSelectedView] = React.useState<'heatmap' | 'treemap'>('heatmap');
  const [selectedSector, setSelectedSector] = React.useState<SectorData | null>(null);

  const handleSectorClick = (sector: SectorData) => {
    setSelectedSector(sector);
    // Could navigate to sector detail or show modal
  };

  const handleRefresh = () => {
    refetch();
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <Link href="/">
            <Button variant="ghost" size="icon">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Sector Performance</h1>
            <p className="text-muted-foreground">
              Market sector analysis and rotation indicators
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={isFetching}
        >
          <RefreshCw className={cn('h-4 w-4 mr-2', isFetching && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {/* Main Heatmap/Treemap View */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Sector Heatmap</CardTitle>
            <CardDescription>
              Performance visualization by market sector
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Tabs
              value={selectedView}
              onValueChange={(v) => setSelectedView(v as 'heatmap' | 'treemap')}
            >
              <TabsList>
                <TabsTrigger value="heatmap" className="gap-1.5">
                  <Grid3X3 className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Heatmap</span>
                </TabsTrigger>
                <TabsTrigger value="treemap" className="gap-1.5">
                  <BarChart3 className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">Treemap</span>
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {selectedView === 'heatmap' ? (
            <SectorHeatmap
              sectors={data?.sectors}
              isLoading={isLoading}
              variant="default"
              showVolume
              onSectorClick={handleSectorClick}
            />
          ) : (
            <>
              <SectorTreemap
                sectors={data?.sectors}
                isLoading={isLoading}
                height={400}
                onSectorClick={handleSectorClick}
              />
              <SectorTreemapLegend />
            </>
          )}
        </CardContent>
      </Card>

      {/* Two-column layout: Rotation Phase + Historical Chart */}
      <div className="grid gap-6 lg:grid-cols-3">
        <RotationPhaseIndicator
          phase={data?.rotationPhase}
          isLoading={isLoading}
        />
        <div className="lg:col-span-2">
          <HistoricalPerformanceChart
            data={data?.historicalPerformance}
            isLoading={isLoading}
          />
        </div>
      </div>

      {/* Sector Rankings Table */}
      <SectorRankingsTable sectors={data?.sectors} isLoading={isLoading} />

      {/* Selected Sector Detail Modal/Card (optional enhancement) */}
      {selectedSector && (
        <Card className="fixed bottom-4 right-4 w-80 shadow-lg z-50">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">{selectedSector.name}</CardTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => setSelectedSector(null)}
              >
                <span className="sr-only">Close</span>
                <span aria-hidden>x</span>
              </Button>
            </div>
            <CardDescription>{selectedSector.symbol}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Daily</span>
              <span
                className={cn(
                  'font-medium',
                  selectedSector.performance >= 0 ? 'text-green-600' : 'text-red-600'
                )}
              >
                {selectedSector.performance >= 0 ? '+' : ''}
                {selectedSector.performance.toFixed(2)}%
              </span>
            </div>
            {selectedSector.weeklyPerformance !== undefined && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Weekly</span>
                <span
                  className={cn(
                    'font-medium',
                    selectedSector.weeklyPerformance >= 0 ? 'text-green-600' : 'text-red-600'
                  )}
                >
                  {selectedSector.weeklyPerformance >= 0 ? '+' : ''}
                  {selectedSector.weeklyPerformance.toFixed(2)}%
                </span>
              </div>
            )}
            {selectedSector.monthlyPerformance !== undefined && (
              <div className="flex justify-between">
                <span className="text-muted-foreground">Monthly</span>
                <span
                  className={cn(
                    'font-medium',
                    selectedSector.monthlyPerformance >= 0 ? 'text-green-600' : 'text-red-600'
                  )}
                >
                  {selectedSector.monthlyPerformance >= 0 ? '+' : ''}
                  {selectedSector.monthlyPerformance.toFixed(2)}%
                </span>
              </div>
            )}
            <Link href={`/stocks?sector=${selectedSector.symbol}`}>
              <Button variant="outline" size="sm" className="w-full mt-2">
                View Stocks
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </Link>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
