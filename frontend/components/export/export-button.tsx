'use client';

import { useState } from 'react';
import { Download, FileJson, FileSpreadsheet, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { downloadFile } from '@/lib/utils/download';

export type ExportFormat = 'csv' | 'json';

export interface ExportOption {
  label: string;
  format: ExportFormat;
  url: string;
  description?: string;
}

interface ExportButtonProps {
  /** Export options to display in dropdown */
  options: ExportOption[];
  /** Button variant */
  variant?: 'default' | 'outline' | 'secondary' | 'ghost';
  /** Button size */
  size?: 'default' | 'sm' | 'lg' | 'icon';
  /** Custom button label */
  label?: string;
  /** Disabled state */
  disabled?: boolean;
  /** Additional class names */
  className?: string;
}

export function ExportButton({
  options,
  variant = 'outline',
  size = 'default',
  label = 'Export',
  disabled = false,
  className,
}: ExportButtonProps) {
  const [isExporting, setIsExporting] = useState(false);
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);

  const handleExport = async (option: ExportOption) => {
    setIsExporting(true);
    setExportingFormat(option.label);

    try {
      await downloadFile(option.url, {
        onStart: () => {
          toast.info(`Starting ${option.label} export...`);
        },
        onComplete: () => {
          toast.success(`${option.label} export completed!`);
        },
        onError: (error) => {
          toast.error(`Export failed: ${error.message}`);
        },
      });
    } finally {
      setIsExporting(false);
      setExportingFormat(null);
    }
  };

  const getFormatIcon = (format: ExportFormat) => {
    switch (format) {
      case 'csv':
        return <FileSpreadsheet className="h-4 w-4" />;
      case 'json':
        return <FileJson className="h-4 w-4" />;
      default:
        return <Download className="h-4 w-4" />;
    }
  };

  // If only one option, render simple button
  if (options.length === 1) {
    const option = options[0];
    return (
      <Button
        variant={variant}
        size={size}
        disabled={disabled || isExporting}
        onClick={() => handleExport(option)}
        className={className}
      >
        {isExporting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          getFormatIcon(option.format)
        )}
        {size !== 'icon' && <span className="ml-2">{label}</span>}
      </Button>
    );
  }

  // Multiple options - render dropdown
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant={variant}
          size={size}
          disabled={disabled || isExporting}
          className={className}
        >
          {isExporting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Download className="h-4 w-4" />
          )}
          {size !== 'icon' && (
            <span className="ml-2">
              {isExporting ? `Exporting ${exportingFormat}...` : label}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Export Format</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {options.map((option, index) => (
          <DropdownMenuItem
            key={index}
            onClick={() => handleExport(option)}
            disabled={isExporting}
          >
            {getFormatIcon(option.format)}
            <span className="ml-2">{option.label}</span>
            {option.description && (
              <span className="ml-2 text-xs text-muted-foreground">
                ({option.description})
              </span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
