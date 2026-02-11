'use client';

import { useState, useEffect, useCallback, FormEvent } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { PortfolioHolding, HoldingCreate, HoldingUpdate } from '@/types';

interface HoldingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Pre-fill for edit mode */
  holding?: PortfolioHolding;
  onSubmit: (data: HoldingCreate | HoldingUpdate) => void;
  isLoading?: boolean;
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(value);
}

export function HoldingDialog({
  open,
  onOpenChange,
  holding,
  onSubmit,
  isLoading = false,
}: HoldingDialogProps) {
  const isEditing = !!holding;

  const [symbol, setSymbol] = useState('');
  const [shares, setShares] = useState('');
  const [costBasis, setCostBasis] = useState('');
  const [notes, setNotes] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Reset form when dialog opens or holding changes
  useEffect(() => {
    if (open) {
      if (holding) {
        setSymbol(holding.symbol);
        setShares(String(holding.shares));
        setCostBasis(String(holding.cost_basis));
        setNotes(holding.notes ?? '');
      } else {
        setSymbol('');
        setShares('');
        setCostBasis('');
        setNotes('');
      }
      setErrors({});
    }
  }, [open, holding]);

  const sharesNum = parseFloat(shares) || 0;
  const costBasisNum = parseFloat(costBasis) || 0;
  const totalCost = sharesNum * costBasisNum;

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {};

    if (!isEditing && !symbol.trim()) {
      newErrors.symbol = 'Symbol is required';
    }

    if (!shares || sharesNum <= 0) {
      newErrors.shares = 'Shares must be greater than 0';
    }

    if (!costBasis || costBasisNum <= 0) {
      newErrors.costBasis = 'Cost basis must be greater than 0';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [isEditing, symbol, shares, sharesNum, costBasis, costBasisNum]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();

    if (!validate()) return;

    if (isEditing) {
      const data: HoldingUpdate = {
        shares: sharesNum,
        cost_basis: costBasisNum,
        notes: notes.trim() || undefined,
      };
      onSubmit(data);
    } else {
      const data: HoldingCreate = {
        symbol: symbol.trim().toUpperCase(),
        shares: sharesNum,
        cost_basis: costBasisNum,
        notes: notes.trim() || undefined,
      };
      onSubmit(data);
    }
  };

  const handleSymbolChange = (value: string) => {
    setSymbol(value.toUpperCase());
    if (errors.symbol) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next.symbol;
        return next;
      });
    }
  };

  const handleSharesChange = (value: string) => {
    setShares(value);
    if (errors.shares) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next.shares;
        return next;
      });
    }
  };

  const handleCostBasisChange = (value: string) => {
    setCostBasis(value);
    if (errors.costBasis) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next.costBasis;
        return next;
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>{isEditing ? 'Edit Holding' : 'Add Holding'}</DialogTitle>
            <DialogDescription>
              {isEditing
                ? `Update the details for ${holding.symbol}.`
                : 'Add a new stock holding to your portfolio.'}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            {/* Symbol */}
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="holding-symbol" className="text-right">
                Symbol
              </Label>
              <div className="col-span-3">
                <Input
                  id="holding-symbol"
                  value={symbol}
                  onChange={(e) => handleSymbolChange(e.target.value)}
                  placeholder="e.g. AAPL"
                  disabled={isEditing}
                  required={!isEditing}
                  aria-invalid={!!errors.symbol}
                />
                {errors.symbol && (
                  <p className="text-destructive text-sm mt-1">{errors.symbol}</p>
                )}
              </div>
            </div>

            {/* Shares */}
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="holding-shares" className="text-right">
                Shares
              </Label>
              <div className="col-span-3">
                <Input
                  id="holding-shares"
                  type="number"
                  step="0.01"
                  min="0"
                  value={shares}
                  onChange={(e) => handleSharesChange(e.target.value)}
                  placeholder="0.00"
                  required
                  aria-invalid={!!errors.shares}
                />
                {errors.shares && (
                  <p className="text-destructive text-sm mt-1">{errors.shares}</p>
                )}
              </div>
            </div>

            {/* Cost Basis */}
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="holding-cost-basis" className="text-right">
                Cost Basis
              </Label>
              <div className="col-span-3">
                <Input
                  id="holding-cost-basis"
                  type="number"
                  step="0.01"
                  min="0"
                  value={costBasis}
                  onChange={(e) => handleCostBasisChange(e.target.value)}
                  placeholder="0.00"
                  required
                  aria-invalid={!!errors.costBasis}
                />
                {errors.costBasis && (
                  <p className="text-destructive text-sm mt-1">{errors.costBasis}</p>
                )}
                <p className="text-muted-foreground text-xs mt-1">Price per share</p>
              </div>
            </div>

            {/* Notes */}
            <div className="grid grid-cols-4 items-start gap-4">
              <Label htmlFor="holding-notes" className="text-right pt-2">
                Notes
              </Label>
              <div className="col-span-3">
                <Textarea
                  id="holding-notes"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Optional notes about this holding..."
                  className="min-h-[80px]"
                />
              </div>
            </div>

            {/* Total Cost Preview */}
            {sharesNum > 0 && costBasisNum > 0 && (
              <div className="grid grid-cols-4 items-center gap-4">
                <Label className="text-right text-muted-foreground">Total Cost</Label>
                <div className="col-span-3">
                  <p className="text-sm font-medium">{formatCurrency(totalCost)}</p>
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {isEditing ? 'Saving...' : 'Adding...'}
                </>
              ) : (
                isEditing ? 'Save Changes' : 'Add'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
