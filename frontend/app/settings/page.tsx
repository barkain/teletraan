'use client';

import { useState } from 'react';
import { Plus, X, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useWatchlist, useUpdateWatchlist } from '@/lib/hooks/use-watchlist';
import { toast } from 'sonner';

export default function SettingsPage() {
  const { data: watchlist, isLoading } = useWatchlist();
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

  if (isLoading) return <div>Loading...</div>;

  return (
    <div className="container mx-auto py-8 px-4">
      <h1 className="text-3xl font-bold mb-8">Settings</h1>

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
            {watchlist?.symbols.map((symbol) => (
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
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
