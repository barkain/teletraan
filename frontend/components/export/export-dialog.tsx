'use client';

import { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { downloadFile } from '@/lib/utils/download';

export type ExportType = 'stock' | 'insights' | 'analysis';
export type ExportFormat = 'csv' | 'json';

interface ExportDialogProps {
  /** Type of export */
  type: ExportType;
  /** Stock symbol (required for stock/analysis exports) */
  symbol?: string;
  /** Current insight filters (for insights export) */
  insightFilters?: {
    type?: string;
    severity?: string;
  };
  /** Trigger button element */
  trigger?: React.ReactNode;
  /** Additional class names */
  className?: string;
}

interface ExportConfig {
  format: ExportFormat;
  startDate: string;
  endDate: string;
  includeIndicators: boolean;
  includeInsights: boolean;
  includeAnnotations: boolean;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function ExportDialog({
  type,
  symbol,
  insightFilters,
  trigger,
  className,
}: ExportDialogProps) {
  const [open, setOpen] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [config, setConfig] = useState<ExportConfig>({
    format: 'json',
    startDate: '',
    endDate: '',
    includeIndicators: true,
    includeInsights: true,
    includeAnnotations: true,
  });

  const buildExportUrl = (): string => {
    const params = new URLSearchParams();

    if (config.startDate) {
      params.set('start_date', config.startDate);
    }
    if (config.endDate) {
      params.set('end_date', config.endDate);
    }

    switch (type) {
      case 'stock':
        if (config.includeIndicators) {
          params.set('include_indicators', 'true');
        }
        const stockQuery = params.toString();
        return `${API_URL}/api/export/stocks/${symbol}/${config.format}${stockQuery ? `?${stockQuery}` : ''}`;

      case 'insights':
        if (insightFilters?.type && insightFilters.type !== 'all') {
          params.set('insight_type', insightFilters.type);
        }
        if (insightFilters?.severity && insightFilters.severity !== 'all') {
          params.set('severity', insightFilters.severity);
        }
        if (config.includeAnnotations) {
          params.set('include_annotations', 'true');
        }
        const insightsQuery = params.toString();
        return `${API_URL}/api/export/insights/${config.format}${insightsQuery ? `?${insightsQuery}` : ''}`;

      case 'analysis':
        params.set('format', config.format);
        if (config.includeIndicators) {
          params.set('include_indicators', 'true');
        }
        if (config.includeInsights) {
          params.set('include_insights', 'true');
        }
        return `${API_URL}/api/export/analysis/${symbol}?${params.toString()}`;

      default:
        throw new Error(`Unknown export type: ${type}`);
    }
  };

  const getTitle = (): string => {
    switch (type) {
      case 'stock':
        return `Export ${symbol} Data`;
      case 'insights':
        return 'Export Insights';
      case 'analysis':
        return `Export ${symbol} Analysis`;
      default:
        return 'Export Data';
    }
  };

  const getDescription = (): string => {
    switch (type) {
      case 'stock':
        return 'Download price history and technical data.';
      case 'insights':
        return 'Download insights matching your current filters.';
      case 'analysis':
        return 'Download complete analysis including prices, indicators, and insights.';
      default:
        return 'Configure export options.';
    }
  };

  const handleExport = async () => {
    setIsExporting(true);

    try {
      const url = buildExportUrl();
      await downloadFile(url, {
        onStart: () => {
          toast.info('Starting export...');
        },
        onComplete: () => {
          toast.success('Export completed!');
          setOpen(false);
        },
        onError: (error) => {
          toast.error(`Export failed: ${error.message}`);
        },
      });
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" className={className}>
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{getTitle()}</DialogTitle>
          <DialogDescription>{getDescription()}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Format Selection */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="format" className="text-right">
              Format
            </Label>
            <Select
              value={config.format}
              onValueChange={(value: ExportFormat) =>
                setConfig({ ...config, format: value })
              }
            >
              <SelectTrigger className="col-span-3">
                <SelectValue placeholder="Select format" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="json">JSON</SelectItem>
                <SelectItem value="csv">CSV</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Date Range (for stock/analysis exports) */}
          {(type === 'stock' || type === 'analysis') && (
            <>
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="startDate" className="text-right">
                  Start Date
                </Label>
                <Input
                  id="startDate"
                  type="date"
                  value={config.startDate}
                  onChange={(e) =>
                    setConfig({ ...config, startDate: e.target.value })
                  }
                  className="col-span-3"
                />
              </div>
              <div className="grid grid-cols-4 items-center gap-4">
                <Label htmlFor="endDate" className="text-right">
                  End Date
                </Label>
                <Input
                  id="endDate"
                  type="date"
                  value={config.endDate}
                  onChange={(e) =>
                    setConfig({ ...config, endDate: e.target.value })
                  }
                  className="col-span-3"
                />
              </div>
            </>
          )}

          {/* Include Options */}
          {(type === 'stock' || type === 'analysis') && (
            <div className="grid grid-cols-4 items-center gap-4">
              <span className="text-right text-sm font-medium">Include</span>
              <div className="col-span-3 flex flex-wrap gap-4">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="indicators"
                    checked={config.includeIndicators}
                    onCheckedChange={(checked) =>
                      setConfig({
                        ...config,
                        includeIndicators: checked === true,
                      })
                    }
                  />
                  <Label htmlFor="indicators" className="text-sm font-normal">
                    Indicators
                  </Label>
                </div>
                {type === 'analysis' && (
                  <div className="flex items-center space-x-2">
                    <Checkbox
                      id="insights"
                      checked={config.includeInsights}
                      onCheckedChange={(checked) =>
                        setConfig({
                          ...config,
                          includeInsights: checked === true,
                        })
                      }
                    />
                    <Label htmlFor="insights" className="text-sm font-normal">
                      Insights
                    </Label>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Annotations option for insights */}
          {type === 'insights' && config.format === 'json' && (
            <div className="grid grid-cols-4 items-center gap-4">
              <span className="text-right text-sm font-medium">Include</span>
              <div className="col-span-3">
                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="annotations"
                    checked={config.includeAnnotations}
                    onCheckedChange={(checked) =>
                      setConfig({
                        ...config,
                        includeAnnotations: checked === true,
                      })
                    }
                  />
                  <Label htmlFor="annotations" className="text-sm font-normal">
                    Annotations
                  </Label>
                </div>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleExport} disabled={isExporting}>
            {isExporting ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Exporting...
              </>
            ) : (
              <>
                <Download className="h-4 w-4 mr-2" />
                Export
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
