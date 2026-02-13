'use client';

import { useState } from 'react';
import { Plus, X, Loader2, Settings2, Cpu } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ConnectionError } from '@/components/ui/empty-state';
import { useWatchlist, useUpdateWatchlist } from '@/lib/hooks/use-watchlist';
import { toast } from 'sonner';

export default function SettingsPage() {
  const { data: watchlist, isLoading, error } = useWatchlist();
  const { mutate: updateWatchlist, isPending } = useUpdateWatchlist();
  const [newSymbol, setNewSymbol] = useState('');

  const addSymbol = () => {
    const symbol = newSymbol.trim().toUpperCase();
    if (symbol && watchlist && !watchlist.symbols.includes(symbol)) {
      updateWatchlist([...watchlist.symbols, symbol], {
        onSuccess: () => {
          toast.success(`Added ${symbol}`);
          setNewSymbol('');
        },
        onError: (err) => toast.error(err.message),
      });
    }
  };

  const removeSymbol = (symbol: string) => {
    if (watchlist) {
      updateWatchlist(watchlist.symbols.filter(s => s !== symbol), {
        onSuccess: () => toast.success(`Removed ${symbol}`),
        onError: (err) => toast.error(err.message),
      });
    }
  };

  return (
    <div className="container mx-auto py-8 px-4">
      <div className="flex items-center gap-2 mb-8">
        <Settings2 className="h-6 w-6 text-primary" />
        <h1 className="text-3xl font-bold">Settings</h1>
      </div>

      <div className="space-y-6">
        {/* LLM Provider Card */}
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Cpu className="h-5 w-5 text-muted-foreground" />
              <CardTitle>LLM Provider</CardTitle>
            </div>
            <CardDescription>
              The AI analysis engine uses Claude via the Claude Code SDK. No API key is required when
              running through Claude Code. For standalone or desktop usage, configure the provider
              in <code className="text-xs bg-muted px-1.5 py-0.5 rounded">backend/.env</code>.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-muted/50 border border-border/50">
              <div className="h-2 w-2 rounded-full bg-green-500" />
              <span className="text-sm font-medium">Claude Code SDK</span>
              <span className="text-xs text-muted-foreground ml-auto">Active provider</span>
            </div>
          </CardContent>
        </Card>

        {/* Connection status when there's an error */}
        {error && <ConnectionError error={error} />}

        {/* Watchlist Card */}
        <Card>
          <CardHeader>
            <CardTitle>Watchlist</CardTitle>
            <CardDescription>
              Manage the stock symbols to track and refresh.
              {watchlist?.last_refresh && (
                <span className="block mt-1 text-xs">
                  Last refreshed: {new Date(watchlist.last_refresh).toLocaleString()}
                </span>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-10 w-full" />
                <div className="flex gap-2">
                  <Skeleton className="h-7 w-16" />
                  <Skeleton className="h-7 w-16" />
                  <Skeleton className="h-7 w-16" />
                </div>
              </div>
            ) : (
              <>
                <div className="flex gap-2 mb-4">
                  <Input
                    placeholder="Enter symbol (e.g., AAPL)"
                    value={newSymbol}
                    onChange={(e) => setNewSymbol(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !isPending && addSymbol()}
                    disabled={isPending}
                  />
                  <Button onClick={addSymbol} variant="outline" disabled={isPending}>
                    {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  </Button>
                </div>

                <div className="flex flex-wrap gap-2">
                  {watchlist?.symbols && watchlist.symbols.length > 0 ? (
                    watchlist.symbols.map((symbol) => (
                      <Badge key={symbol} variant="secondary" className="pl-3 pr-1 py-1">
                        {symbol}
                        <button
                          onClick={() => removeSymbol(symbol)}
                          disabled={isPending}
                          className="ml-2 hover:bg-destructive/20 rounded-full p-0.5 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </Badge>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No symbols in watchlist. Add one above to get started.
                    </p>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
