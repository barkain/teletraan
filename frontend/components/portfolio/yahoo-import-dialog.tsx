'use client';

import { useState, useRef, DragEvent } from 'react';
import { Upload, Loader2, FileText, X, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { useImportHoldings } from '@/lib/hooks/use-portfolio';
import type { ImportResult } from '@/types';

interface YahooImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function YahooImportDialog({ open, onOpenChange }: YahooImportDialogProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const importHoldings = useImportHoldings();

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setSelectedFile(null);
      setImportResult(null);
      setIsDragging(false);
      importHoldings.reset();
    }
    onOpenChange(next);
  };

  const handleFileSelect = (file: File) => {
    if (!file.name.endsWith('.csv')) {
      toast.error('Please select a CSV file');
      return;
    }
    setSelectedFile(file);
    setImportResult(null);
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  };

  const handleImport = () => {
    if (!selectedFile) return;
    importHoldings.mutate(selectedFile, {
      onSuccess: (result) => {
        setImportResult(result);
        toast.success(`Imported ${result.imported} holdings`);
      },
      onError: (err) => {
        toast.error(`Import failed: ${err.message}`);
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Import from Yahoo Finance</DialogTitle>
          <DialogDescription>Upload your Yahoo Finance portfolio CSV</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <ol className="list-decimal list-inside space-y-1 text-sm text-muted-foreground">
            <li>Go to finance.yahoo.com and open your portfolio</li>
            <li>Click the download/export icon to save as CSV</li>
            <li>Upload the CSV file below</li>
          </ol>

          <div
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              isDragging ? 'border-primary bg-primary/5' : 'border-muted-foreground/25'
            }`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFileSelect(file);
              }}
            />
            {selectedFile ? (
              <div className="flex items-center justify-center gap-2">
                <FileText className="h-5 w-5 text-muted-foreground" />
                <span className="text-sm font-medium">{selectedFile.name}</span>
                <button
                  type="button"
                  className="ml-1 rounded-full p-1 hover:bg-muted"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFile(null);
                    setImportResult(null);
                    if (fileInputRef.current) fileInputRef.current.value = '';
                  }}
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <Upload className="h-8 w-8" />
                <span className="text-sm">Click to select CSV file</span>
              </div>
            )}
          </div>

          {importResult && (
            <div className="rounded-lg border bg-muted/50 p-4 space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                Imported: {importResult.created} new, {importResult.updated} updated, {importResult.skipped} skipped
              </div>
              {importResult.warnings.length > 0 && (
                <ul className="text-sm text-muted-foreground space-y-1">
                  {importResult.warnings.map((w, i) => (
                    <li key={i} className="text-yellow-600">⚠ {w}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleImport} disabled={!selectedFile || importHoldings.isPending}>
            {importHoldings.isPending ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Importing...
              </>
            ) : (
              'Import'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
