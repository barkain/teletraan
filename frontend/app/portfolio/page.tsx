'use client';

import { useRef, useState } from 'react';
import { Card, CardContent, CardDescription, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { HoldingsTable } from '@/components/portfolio/holdings-table';
import { HoldingDialog } from '@/components/portfolio/holding-dialog';
import { PortfolioSummary } from '@/components/portfolio/portfolio-summary';
import { PortfolioImpact } from '@/components/portfolio/portfolio-impact';
import { YahooImportDialog } from '@/components/portfolio/yahoo-import-dialog';
import {
  usePortfolio,
  usePortfolioImpact,
  useAddHolding,
  useUpdateHolding,
  useDeleteHolding,
  useImportHoldings,
  useDeleteAllHoldings,
  portfolioKeys,
} from '@/lib/hooks/use-portfolio';
import { api } from '@/lib/api';
import { useQueryClient } from '@tanstack/react-query';
import type { PortfolioHolding, HoldingCreate, HoldingUpdate } from '@/types';
import { Briefcase, Download, Loader2, Plus, RefreshCw, Trash2, Upload, Wifi, WifiOff } from 'lucide-react';
import { ConnectionError } from '@/components/ui/empty-state';
import { toast } from 'sonner';

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

function EmptyState({ onAdd, onImport, onYahoo, onIbkr, isImporting }: { onAdd: () => void; onImport: () => void; onYahoo: () => void; onIbkr: () => void; isImporting: boolean }) {
  return (
    <Card className="py-12">
      <CardContent className="flex flex-col items-center justify-center text-center">
        {isImporting ? (
          <>
            <svg className="animate-spin h-12 w-12 text-primary mb-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <CardTitle className="text-lg">Importing holdings...</CardTitle>
          </>
        ) : (
          <>
            <div className="rounded-full bg-muted p-4 mb-4">
              <Briefcase className="h-8 w-8 text-muted-foreground" />
            </div>
            <CardTitle className="text-lg mb-2">No Holdings Yet</CardTitle>
            <CardDescription className="max-w-sm mb-6">
              Add your first holding to get started, or import from a CSV file.
              Track your portfolio performance and see how AI insights impact your investments.
            </CardDescription>
            <div className="flex items-center gap-2">
              <Button onClick={onAdd} className="gap-2">
                <Plus className="h-4 w-4" />
                Add Your First Holding
              </Button>
              <Button variant="outline" onClick={onImport} className="gap-2">
                <Upload className="h-4 w-4" />
                Import CSV
              </Button>
              <Button variant="outline" onClick={onYahoo} className="gap-2">
                <Upload className="h-4 w-4" />
                Yahoo Import
              </Button>
              <Button variant="outline" onClick={onIbkr} className="gap-2">
                <Wifi className="h-4 w-4" />
                Sync from IBKR
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function PortfolioPage() {
  const [holdingDialogOpen, setHoldingDialogOpen] = useState(false);
  const [editingHolding, setEditingHolding] = useState<PortfolioHolding | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [ibkrDialogOpen, setIbkrDialogOpen] = useState(false);
  const [ibkrAccountId, setIbkrAccountId] = useState('');
  const [ibkrSyncing, setIbkrSyncing] = useState(false);
  const [yahooDialogOpen, setYahooDialogOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const queryClient = useQueryClient();

  // Data hooks
  const { data: portfolio, isLoading, error } = usePortfolio();
  const hasHoldings = (portfolio?.holdings?.length ?? 0) > 0;
  const { data: impact, isLoading: impactLoading } = usePortfolioImpact(hasHoldings);

  // Mutation hooks
  const addHolding = useAddHolding();
  const updateHolding = useUpdateHolding();
  const deleteHolding = useDeleteHolding();
  const importHoldings = useImportHoldings();
  const deleteAllHoldings = useDeleteAllHoldings();

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

  const handleImportClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    importHoldings.mutate(file, {
      onSuccess: (result) => {
        toast.success(`Imported ${result.imported} holdings (${result.created} new, ${result.updated} updated)`);
        if (result.warnings.length > 0) {
          toast.warning(`${result.skipped} rows skipped`);
        }
      },
      onError: (err) => {
        toast.error(`Import failed: ${err.message}`);
      },
    });
    // Reset so the same file can be re-selected
    e.target.value = '';
  };

  const handleExport = () => {
    window.open(api.portfolio.exportCsvUrl(), '_blank');
  };

  const handleDeleteAll = () => {
    deleteAllHoldings.mutate(undefined, {
      onSuccess: (result) => {
        toast.success(`Deleted ${result.deleted_count} holdings`);
      },
      onError: (err) => {
        toast.error(`Delete failed: ${err.message}`);
      },
    });
  };

  const handleIbkrSync = async () => {
    if (!portfolio || !ibkrAccountId.trim()) return;
    setIbkrSyncing(true);
    try {
      const result = await api.portfolio.ibkrSync(portfolio.id, ibkrAccountId.trim());
      await queryClient.invalidateQueries({ queryKey: portfolioKeys.all });
      setIbkrDialogOpen(false);
      toast.success(`IBKR sync complete: ${result.added} added, ${result.updated} updated`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Sync failed';
      toast.error(`IBKR sync failed: ${msg}`);
    } finally {
      setIbkrSyncing(false);
    }
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
            <Button variant="outline" size="sm" onClick={handleExport}>
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
            <Button variant="outline" size="sm" onClick={handleImportClick} disabled={importHoldings.isPending}>
              {importHoldings.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Upload className="h-4 w-4 mr-2" />}
              {importHoldings.isPending ? 'Importing...' : 'Import'}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" disabled={deleteAllHoldings.isPending}>
                  {deleteAllHoldings.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Trash2 className="h-4 w-4 mr-2" />}
                  {deleteAllHoldings.isPending ? 'Deleting...' : 'Delete All'}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete all holdings?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will permanently delete all {portfolio?.holdings?.length ?? 0} holdings from your portfolio. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={handleDeleteAll} className="bg-destructive text-destructive-foreground hover:bg-destructive/90">
                    Delete All
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isRefreshing}>
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
              Update Prices
            </Button>
            <Button variant="outline" size="sm" onClick={() => setYahooDialogOpen(true)}>
              <Upload className="h-4 w-4 mr-2" />
              Yahoo Import
            </Button>
            <Button variant="outline" size="sm" onClick={() => { setIbkrAccountId(portfolio?.ibkr_account_id ?? ''); setIbkrDialogOpen(true); }} title="Sync from Interactive Brokers">
              {portfolio?.ibkr_last_synced_at ? (
                <Wifi className="h-4 w-4 mr-2 text-green-500" />
              ) : (
                <WifiOff className="h-4 w-4 mr-2 text-muted-foreground" />
              )}
              IBKR Sync
            </Button>
            <Button onClick={handleOpenAddDialog} className="gap-2">
              <Plus className="h-4 w-4" />
              Add Holding
            </Button>
          </div>
        )}
      </div>

      {/* IBKR Sync Dialog */}
      <Dialog open={ibkrDialogOpen} onOpenChange={setIbkrDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Sync from Interactive Brokers</DialogTitle>
            <DialogDescription>
              Enter your IBKR account ID to pull live positions into this portfolio.
              The IBKR Client Portal Gateway must be running and authenticated at{' '}
              <code className="text-xs bg-muted px-1 py-0.5 rounded">localhost:5000</code>.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="ibkr-account">Account ID</Label>
              <Input
                id="ibkr-account"
                placeholder="e.g. DU1234567"
                value={ibkrAccountId}
                onChange={(e) => setIbkrAccountId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleIbkrSync()}
              />
            </div>
            {portfolio?.ibkr_last_synced_at && (
              <p className="text-xs text-muted-foreground">
                Last synced: {new Date(portfolio.ibkr_last_synced_at).toLocaleString()}
                {portfolio.ibkr_account_id && ` (${portfolio.ibkr_account_id})`}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIbkrDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleIbkrSync} disabled={ibkrSyncing || !ibkrAccountId.trim()}>
              {ibkrSyncing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
              {ibkrSyncing ? 'Syncing...' : 'Sync Now'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Content */}
      {isLoading ? (
        <PortfolioSkeleton />
      ) : error ? (
        <ConnectionError error={error} />
      ) : !portfolio || !hasHoldings ? (
        <EmptyState onAdd={handleOpenAddDialog} onImport={handleImportClick} onYahoo={() => setYahooDialogOpen(true)} onIbkr={() => { setIbkrAccountId(portfolio?.ibkr_account_id ?? ''); setIbkrDialogOpen(true); }} isImporting={importHoldings.isPending} />
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

      {/* Hidden file input for CSV import */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Yahoo Import Dialog */}
      <YahooImportDialog open={yahooDialogOpen} onOpenChange={setYahooDialogOpen} />

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
