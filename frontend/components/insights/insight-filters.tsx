'use client';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Search, X } from 'lucide-react';
import type { InsightFilters as InsightFiltersType, InsightType, InsightSeverity } from '@/types';

// Helper to format date as YYYY-MM-DD for input[type="date"]
function formatDateForInput(date: Date): string {
  return date.toISOString().split('T')[0];
}

// Get default date range (30 days ago to today)
function getDefaultDateRange() {
  const endDate = new Date();
  const startDate = new Date();
  startDate.setDate(startDate.getDate() - 30);
  return {
    startDate: formatDateForInput(startDate),
    endDate: formatDateForInput(endDate),
  };
}

interface InsightFiltersProps {
  filters: InsightFiltersType;
  onFiltersChange: (filters: InsightFiltersType) => void;
}

const insightTypes: { value: InsightType | 'all'; label: string }[] = [
  { value: 'all', label: 'All Types' },
  { value: 'pattern', label: 'Pattern' },
  { value: 'anomaly', label: 'Anomaly' },
  { value: 'sector', label: 'Sector' },
  { value: 'technical', label: 'Technical' },
  { value: 'economic', label: 'Economic' },
];

const insightSeverities: { value: InsightSeverity | 'all'; label: string }[] = [
  { value: 'all', label: 'All Severities' },
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'alert', label: 'Alert' },
];

export function InsightFilters({ filters, onFiltersChange }: InsightFiltersProps) {
  const defaultDates = getDefaultDateRange();

  // Only show "Clear Filters" if user has actively modified filters beyond defaults
  // Date filters matching defaults don't count as "active"
  const hasActiveFilters =
    (filters.type && filters.type !== 'all') ||
    (filters.severity && filters.severity !== 'all') ||
    filters.search ||
    (filters.startDate && filters.startDate !== defaultDates.startDate) ||
    (filters.endDate && filters.endDate !== defaultDates.endDate);

  const handleClearFilters = () => {
    // Reset to defaults (including default date range)
    onFiltersChange({
      type: 'all',
      severity: 'all',
      search: '',
      startDate: defaultDates.startDate,
      endDate: defaultDates.endDate,
      page: 1,
    });
  };

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:flex-wrap">
      {/* Search Input */}
      <div className="relative flex-1 min-w-[200px] max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search insights..."
          value={filters.search || ''}
          onChange={(e) =>
            onFiltersChange({ ...filters, search: e.target.value, page: 1 })
          }
          className="pl-9"
        />
      </div>

      {/* Type Filter */}
      <Select
        value={filters.type || 'all'}
        onValueChange={(value) =>
          onFiltersChange({ ...filters, type: value as InsightType | 'all', page: 1 })
        }
      >
        <SelectTrigger className="w-[150px]">
          <SelectValue placeholder="Type" />
        </SelectTrigger>
        <SelectContent>
          {insightTypes.map((type) => (
            <SelectItem key={type.value} value={type.value}>
              {type.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Severity Filter */}
      <Select
        value={filters.severity || 'all'}
        onValueChange={(value) =>
          onFiltersChange({ ...filters, severity: value as InsightSeverity | 'all', page: 1 })
        }
      >
        <SelectTrigger className="w-[150px]">
          <SelectValue placeholder="Severity" />
        </SelectTrigger>
        <SelectContent>
          {insightSeverities.map((severity) => (
            <SelectItem key={severity.value} value={severity.value}>
              {severity.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Date Range - Optional */}
      <div className="flex items-center gap-2">
        <Input
          type="date"
          placeholder="Start Date"
          value={filters.startDate || ''}
          onChange={(e) =>
            onFiltersChange({ ...filters, startDate: e.target.value || undefined, page: 1 })
          }
          className="w-[140px]"
        />
        <span className="text-muted-foreground">to</span>
        <Input
          type="date"
          placeholder="End Date"
          value={filters.endDate || ''}
          onChange={(e) =>
            onFiltersChange({ ...filters, endDate: e.target.value || undefined, page: 1 })
          }
          className="w-[140px]"
        />
      </div>

      {/* Clear Filters */}
      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          onClick={handleClearFilters}
          className="gap-1"
        >
          <X className="h-4 w-4" />
          Clear Filters
        </Button>
      )}
    </div>
  );
}
