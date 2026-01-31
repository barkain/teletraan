'use client';

import { StatsCards } from '@/components/dashboard/stats-cards';
import { MarketOverview } from '@/components/dashboard/market-overview';
import { InsightsSummary } from '@/components/dashboard/insights-summary';
import { SectorOverview } from '@/components/dashboard/sector-overview';
import { RefreshDataButton } from '@/components/refresh-data-button';
import { useMarketOverview, useRecentInsights } from '@/lib/hooks/use-market-data';

export default function DashboardPage() {
  const { data: marketData, isLoading: isMarketLoading } = useMarketOverview();
  const { data: insights, isLoading: isInsightsLoading } = useRecentInsights(5);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground">
            Your market overview and latest insights
          </p>
        </div>
        <RefreshDataButton />
      </div>

      {/* Stats Cards */}
      <StatsCards
        stats={marketData?.stats}
        isLoading={isMarketLoading}
      />

      {/* Market Overview */}
      <div>
        <h2 className="text-xl font-semibold mb-4">Market Overview</h2>
        <MarketOverview
          indices={marketData?.indices}
          isLoading={isMarketLoading}
        />
      </div>

      {/* Two-column grid: Insights and Sectors */}
      <div className="grid gap-6 lg:grid-cols-2">
        <InsightsSummary
          insights={insights}
          isLoading={isInsightsLoading}
        />
        <SectorOverview
          sectors={marketData?.sectors}
          isLoading={isMarketLoading}
        />
      </div>
    </div>
  );
}
