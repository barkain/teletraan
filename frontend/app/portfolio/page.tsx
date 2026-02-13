'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { HoldingsTable } from '@/components/portfolio/holdings-table';
import { HoldingDialog } from '@/components/portfolio/holding-dialog';
import { PortfolioSummary } from '@/components/portfolio/portfolio-summary';
import { PortfolioImpact } from '@/components/portfolio/portfolio-impact';
import {
  usePortfolio,
  usePortfolioImpact,
  useAddHolding,
  useUpdateHolding,
  useDeleteHolding,
  portfolioKeys,
} from '@/lib/hooks/use-portfolio';
import { useQueryClient } from '@tanstack/react-query';
import type { PortfolioHolding, HoldingCreate, HoldingUpdate } from '@/types';
import { Briefcase, Plus, RefreshCw } from 'lucide-react';
import { ConnectionError } from '@/components/ui/empty-state';

function PortfolioSkeleton() {
  return (
    <div className="space-y-6">
      {/* Summary skeleton */}
      <Card>
        <div className="p-6">
          <Skeleton className="h-6 w-40 mb-4" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-32" />
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* Table skeleton */}
      <Card>
        <div className="p-6 space-y-3">
          <Skeleton className="h-8 w-full" />
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </Card>
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        <div className="rounded-full bg-muted p-4 mb-4">
          <Briefcase className="h-8 w-8 text-muted-foreground" />
        </div>
        <CardTitle className="text-lg mb-2">No Holdings Yet</CardTitle>
        <CardDescription className="max-w-sm mb-6">
          Add your first holding to get started. Track your portfolio performance
          and see how AI insights impact your investments.
        </CardDescription>
        <Button onClick={onAdd} className="gap-2">
          <Plus className="h-4 w-4" />
          Add Your First Holding
        </Button>
      </CardContent>
    </Card>
  );
}

export default function PortfolioPage() {
  const [holdingDialogOpen, setHoldingDialogOpen] = useState(false);
  const [editingHolding, setEditingHolding] = useState<PortfolioHolding | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const queryClient = useQueryClient();

  // Data hooks
  const { data: portfolio, isLoading, error } = usePortfolio();
  const hasHoldings = (portfolio?.holdings?.length ?? 0) > 0;
  const { data: impact, isLoading: impactLoading } = usePortfolioImpact(hasHoldings);

  // Mutation hooks
  const addHolding = useAddHolding();
  const updateHolding = useUpdateHolding();
  const deleteHolding = useDeleteHolding();

  const isMutating = addHolding.isPending || updateHolding.isPending;

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await queryClient.invalidateQueries({ queryKey: portfolioKeys.all });
    setTimeout(() => setIsRefreshing(false), 1000);
  };

  const handleOpenAddDialog = () => {
    setEditingHolding(null);
    setHoldingDialogOpen(true);
  };

  const handleOpenEditDialog = (holding: PortfolioHolding) => {
    setEditingHolding(holding);
    setHoldingDialogOpen(true);
  };

  const handleDeleteHolding = (holdingId: number) => {
    deleteHolding.mutate(holdingId);
  };

  const handleDialogSubmit = (data: HoldingCreate | HoldingUpdate) => {
    if (editingHolding) {
      updateHolding.mutate(
        { holdingId: editingHolding.id, data: data as HoldingUpdate },
        {
          onSuccess: () => {
            setHoldingDialogOpen(false);
            setEditingHolding(null);
          },
        }
      );
    } else {
      addHolding.mutate(data as HoldingCreate, {
        onSuccess: () => {
          setHoldingDialogOpen(false);
        },
      });
    }
  };

  const handleDialogOpenChange = (open: boolean) => {
    setHoldingDialogOpen(open);
    if (!open) {
      setEditingHolding(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Briefcase className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight">Portfolio</h1>
          </div>
          <p className="text-muted-foreground mt-1">
            Track your holdings and see how AI insights impact your investments
          </p>
        </div>
        {hasHoldings && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isRefreshing}>
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
              Update Prices
            </Button>
            <Button onClick={handleOpenAddDialog} className="gap-2">
              <Plus className="h-4 w-4" />
              Add Holding
            </Button>
          </div>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <PortfolioSkeleton />
      ) : error ? (
        <ConnectionError error={error} />
      ) : !portfolio || !hasHoldings ? (
        <EmptyState onAdd={handleOpenAddDialog} />
      ) : (
        <>
          {/* Portfolio Summary */}
          <PortfolioSummary portfolio={portfolio} />

          {/* Holdings Table */}
          <Card>
            <CardContent className="p-0">
              <HoldingsTable
                holdings={portfolio.holdings}
                onEdit={handleOpenEditDialog}
                onDelete={handleDeleteHolding}
              />
            </CardContent>
          </Card>

          {/* Portfolio Impact */}
          <PortfolioImpact impact={impact} isLoading={impactLoading} />
        </>
      )}

      {/* Holding Dialog */}
      <HoldingDialog
        open={holdingDialogOpen}
        onOpenChange={handleDialogOpenChange}
        holding={editingHolding ?? undefined}
        onSubmit={handleDialogSubmit}
        isLoading={isMutating}
      />
    </div>
  );
}
