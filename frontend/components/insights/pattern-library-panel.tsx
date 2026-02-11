'use client';

import { useState, useMemo } from 'react';
import {
  BookOpen, Brain, ChevronDown, ChevronUp, Search, Grid, List,
  TrendingUp, Zap, RefreshCcw, Calendar, BarChart3, Target,
  CircleSlash, SortAsc, SortDesc, X, Hash
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import type {
  PatternType,
  KnowledgePattern,
  ConversationTheme,
  ThemeType,
} from '@/lib/types/knowledge';

interface PatternLibraryPanelProps {
  patterns?: KnowledgePattern[];
  themes?: ConversationTheme[];
  patternType?: PatternType;
  minSuccessRate?: number;
  onPatternSelect?: (pattern: KnowledgePattern) => void;
  onThemeSelect?: (theme: ConversationTheme) => void;
  isLoading?: boolean;
  className?: string;
}

// Pattern type configuration with colors and icons
const patternTypeConfig: Record<PatternType, { color: string; borderColor: string; icon: typeof TrendingUp; label: string }> = {
  TECHNICAL_SETUP: { color: 'bg-blue-500', borderColor: 'border-l-blue-500', icon: TrendingUp, label: 'Technical Setup' },
  MACRO_CORRELATION: { color: 'bg-purple-500', borderColor: 'border-l-purple-500', icon: RefreshCcw, label: 'Macro Correlation' },
  SECTOR_ROTATION: { color: 'bg-green-500', borderColor: 'border-l-green-500', icon: Zap, label: 'Sector Rotation' },
  EARNINGS_PATTERN: { color: 'bg-amber-500', borderColor: 'border-l-amber-500', icon: Calendar, label: 'Earnings Pattern' },
  SEASONALITY: { color: 'bg-cyan-500', borderColor: 'border-l-cyan-500', icon: BarChart3, label: 'Seasonality' },
  CROSS_ASSET: { color: 'bg-pink-500', borderColor: 'border-l-pink-500', icon: Target, label: 'Cross Asset' },
};

// Theme type configuration
const themeTypeConfig: Record<ThemeType, { color: string; label: string }> = {
  MARKET_REGIME: { color: 'bg-blue-600', label: 'Market Regime' },
  SECTOR_TREND: { color: 'bg-green-600', label: 'Sector Trend' },
  MACRO_THEME: { color: 'bg-purple-600', label: 'Macro Theme' },
  FACTOR_ROTATION: { color: 'bg-amber-600', label: 'Factor Rotation' },
  RISK_CONCERN: { color: 'bg-red-600', label: 'Risk Concern' },
  OPPORTUNITY_THESIS: { color: 'bg-emerald-600', label: 'Opportunity Thesis' },
};

type SortOption = 'success_rate' | 'occurrences' | 'last_triggered';

/**
 * Format a timestamp into a relative time string (e.g., "2 hours ago")
 */
function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) {
    return 'just now';
  } else if (diffMins < 60) {
    return `${diffMins}m ago`;
  } else if (diffHours < 24) {
    return `${diffHours}h ago`;
  } else if (diffDays < 7) {
    return `${diffDays}d ago`;
  } else {
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  }
}

/**
 * Format trigger conditions as readable list
 */
function formatTriggerConditions(conditions: Record<string, unknown>): string[] {
  return Object.entries(conditions).map(([key, value]) => {
    const formattedKey = key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    if (typeof value === 'object' && value !== null) {
      return `${formattedKey}: ${JSON.stringify(value)}`;
    }
    return `${formattedKey}: ${value}`;
  });
}

/**
 * Get freshness indicator color based on how recently a pattern was active
 * Green: within 7 days, Amber: within 30 days, Gray: older than 30 days
 */
function getFreshnessColor(pattern: KnowledgePattern): string {
  const timestamp = pattern.last_triggered_at || pattern.updated_at;
  if (!timestamp) return 'bg-gray-400';

  const date = new Date(timestamp);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - date.getTime()) / 86400000);

  if (diffDays <= 7) return 'bg-green-500';
  if (diffDays <= 30) return 'bg-amber-500';
  return 'bg-gray-400';
}

/**
 * Success rate ring component
 */
function SuccessRateRing({ rate, size = 48 }: { rate: number; size?: number }) {
  const percentage = Math.round(rate * 100);
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (rate * circumference);

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="rotate-[-90deg]" width={size} height={size}>
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={4}
          className="text-muted/30"
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={4}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          className={cn(
            percentage >= 70 ? 'text-green-500' :
            percentage >= 50 ? 'text-amber-500' : 'text-red-500'
          )}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-xs font-bold">{percentage}%</span>
      </div>
    </div>
  );
}

/**
 * Pattern card component — redesigned with trigger chips, freshness, and action summary
 */
function PatternCard({
  pattern,
  onSelect,
}: {
  pattern: KnowledgePattern;
  onSelect: (pattern: KnowledgePattern) => void;
}) {
  const typeConfig = patternTypeConfig[pattern.pattern_type];
  const TypeIcon = typeConfig.icon;
  const freshnessColor = getFreshnessColor(pattern);
  const triggerConditions = formatTriggerConditions(pattern.trigger_conditions);
  const hasConditions = triggerConditions.length > 0;
  const visibleConditions = triggerConditions.slice(0, 3);
  const overflowCount = triggerConditions.length - 3;
  const symbols = pattern.related_symbols ?? [];
  const visibleSymbols = symbols.slice(0, 3);
  const symbolOverflow = symbols.length - 3;

  // Trading action summary: expected_outcome or truncated description
  const actionSummary = pattern.expected_outcome
    ? pattern.expected_outcome
    : pattern.description.length > 100
      ? pattern.description.slice(0, 100) + '...'
      : pattern.description;

  return (
    <Card
      className={cn(
        'border-l-4 hover:shadow-md transition-all cursor-pointer',
        typeConfig.borderColor,
        !pattern.is_active && 'opacity-60'
      )}
      onClick={() => onSelect(pattern)}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            {/* Type Badge — small rounded pill */}
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium text-white mb-2',
                typeConfig.color
              )}
            >
              <TypeIcon className="w-3 h-3 mr-1" />
              {typeConfig.label}
            </span>

            {/* Pattern Name */}
            <CardTitle className="text-base font-bold line-clamp-2">
              {pattern.pattern_name}
            </CardTitle>
          </div>

          {/* Success Rate Ring — 48px */}
          <SuccessRateRing rate={pattern.success_rate} size={48} />
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-3">
        {/* Trading Action Summary */}
        <p className="text-sm font-medium text-foreground/80 line-clamp-1">
          {actionSummary}
        </p>

        {/* Trigger Condition Chips */}
        {hasConditions && (
          <div className="flex flex-wrap items-center gap-1.5">
            {visibleConditions.map((condition, i) => (
              <span
                key={i}
                className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {condition}
              </span>
            ))}
            {overflowCount > 0 && (
              <span className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground font-medium">
                +{overflowCount} more
              </span>
            )}
          </div>
        )}

        {/* Meta Row */}
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          {/* Occurrences */}
          <div className="flex items-center gap-1">
            <Hash className="w-3 h-3" />
            <span>{pattern.occurrences} triggers</span>
          </div>

          {/* Related Symbols */}
          {visibleSymbols.length > 0 && (
            <div className="flex items-center gap-1">
              {visibleSymbols.map((symbol) => (
                <Badge key={symbol} variant="outline" className="text-[10px] px-1.5 py-0 h-5 font-mono">
                  {symbol}
                </Badge>
              ))}
              {symbolOverflow > 0 && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5">
                  +{symbolOverflow}
                </Badge>
              )}
            </div>
          )}

          {/* Date with freshness dot */}
          {(pattern.last_triggered_at || pattern.updated_at) && (
            <div className="flex items-center gap-1.5">
              <span
                className={cn('inline-block w-1.5 h-1.5 rounded-full', freshnessColor)}
                title={
                  freshnessColor === 'bg-green-500'
                    ? 'Active within 7 days'
                    : freshnessColor === 'bg-amber-500'
                      ? 'Active within 30 days'
                      : 'Inactive over 30 days'
                }
              />
              <Calendar className="w-3 h-3" />
              <span>
                {formatRelativeTime(pattern.last_triggered_at || pattern.updated_at!)}
              </span>
            </div>
          )}

          {/* Inactive indicator */}
          {!pattern.is_active && (
            <div className="flex items-center gap-1 text-yellow-600">
              <CircleSlash className="w-3 h-3" />
              <span>Inactive</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Theme card component
 */
function ThemeCard({
  theme,
  onSelect,
}: {
  theme: ConversationTheme;
  onSelect?: (theme: ConversationTheme) => void;
}) {
  const typeConfig = themeTypeConfig[theme.theme_type];

  return (
    <div
      className="p-3 rounded-lg border bg-card hover:shadow-sm transition-shadow cursor-pointer"
      onClick={() => onSelect?.(theme)}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <Badge className={`${typeConfig.color} text-white text-xs mb-1`}>
            {typeConfig.label}
          </Badge>
          <h4 className="text-sm font-semibold line-clamp-1">{theme.theme_name}</h4>
        </div>
        <div className="text-right">
          <div className="text-xs text-muted-foreground">Relevance</div>
          <div className="text-sm font-bold">{Math.round(theme.current_relevance * 100)}%</div>
        </div>
      </div>

      {/* Relevance Bar */}
      <Progress value={theme.current_relevance * 100} className="h-1.5 mb-2" />

      {/* Tags */}
      <div className="flex flex-wrap gap-1">
        {theme.related_symbols.slice(0, 3).map((symbol) => (
          <Badge key={symbol} variant="outline" className="text-xs">
            {symbol}
          </Badge>
        ))}
        {theme.related_sectors.slice(0, 2).map((sector) => (
          <Badge key={sector} variant="secondary" className="text-xs">
            {sector}
          </Badge>
        ))}
        {(theme.related_symbols.length > 3 || theme.related_sectors.length > 2) && (
          <Badge variant="secondary" className="text-xs">
            +{theme.related_symbols.length - 3 + theme.related_sectors.length - 2}
          </Badge>
        )}
      </div>
    </div>
  );
}

/**
 * PatternLibraryPanel - Browse and explore validated trading patterns
 */
export function PatternLibraryPanel({
  patterns = [],
  themes = [],
  patternType: initialPatternType,
  minSuccessRate: initialMinSuccessRate,
  onPatternSelect,
  onThemeSelect,
  isLoading = false,
  className,
}: PatternLibraryPanelProps) {
  // Filter and view state
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedPatternType, setSelectedPatternType] = useState<PatternType | 'all'>(
    initialPatternType || 'all'
  );
  const [minSuccessRate, setMinSuccessRate] = useState(initialMinSuccessRate || 0);
  const [sortBy, setSortBy] = useState<SortOption>('success_rate');
  const [sortDesc, setSortDesc] = useState(true);
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [isThemesExpanded, setIsThemesExpanded] = useState(true);

  // Compute counts per pattern type (respecting search and success rate, but not type filter)
  const patternTypeCounts = useMemo(() => {
    let base = patterns;

    // Apply search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      base = base.filter(
        (p) =>
          p.pattern_name.toLowerCase().includes(query) ||
          p.description.toLowerCase().includes(query)
      );
    }

    // Apply min success rate filter
    if (minSuccessRate > 0) {
      base = base.filter((p) => p.success_rate >= minSuccessRate / 100);
    }

    const counts: Partial<Record<PatternType, number>> = {};
    for (const p of base) {
      counts[p.pattern_type] = (counts[p.pattern_type] || 0) + 1;
    }
    return counts;
  }, [patterns, searchQuery, minSuccessRate]);

  // Filter and sort patterns
  const filteredPatterns = useMemo(() => {
    let filtered = patterns;

    // Filter by type
    if (selectedPatternType !== 'all') {
      filtered = filtered.filter((p) => p.pattern_type === selectedPatternType);
    }

    // Filter by min success rate
    if (minSuccessRate > 0) {
      filtered = filtered.filter((p) => p.success_rate >= minSuccessRate / 100);
    }

    // Filter by search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (p) =>
          p.pattern_name.toLowerCase().includes(query) ||
          p.description.toLowerCase().includes(query)
      );
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      let comparison = 0;
      switch (sortBy) {
        case 'success_rate':
          comparison = a.success_rate - b.success_rate;
          break;
        case 'occurrences':
          comparison = a.occurrences - b.occurrences;
          break;
        case 'last_triggered':
          const dateA = a.last_triggered_at ? new Date(a.last_triggered_at).getTime() : 0;
          const dateB = b.last_triggered_at ? new Date(b.last_triggered_at).getTime() : 0;
          comparison = dateA - dateB;
          break;
      }
      return sortDesc ? -comparison : comparison;
    });

    return filtered;
  }, [patterns, selectedPatternType, minSuccessRate, searchQuery, sortBy, sortDesc]);

  // Filter themes by relevance
  const sortedThemes = useMemo(() => {
    return [...themes].sort((a, b) => b.current_relevance - a.current_relevance);
  }, [themes]);

  const hasActiveFilters =
    selectedPatternType !== 'all' ||
    minSuccessRate > 0 ||
    searchQuery.length > 0;

  const handleClearFilters = () => {
    setSearchQuery('');
    setSelectedPatternType('all');
    setMinSuccessRate(0);
  };

  return (
    <div className={cn('flex flex-col h-full', className)}>
      {/* Header */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-semibold">Pattern Library</h2>
          <Badge variant="secondary" className="ml-1">
            {filteredPatterns.length}
          </Badge>
        </div>

        {/* View Toggle */}
        <div className="flex items-center gap-1">
          <Button
            variant={viewMode === 'grid' ? 'default' : 'ghost'}
            size="icon"
            className="h-8 w-8"
            onClick={() => setViewMode('grid')}
          >
            <Grid className="h-4 w-4" />
          </Button>
          <Button
            variant={viewMode === 'list' ? 'default' : 'ghost'}
            size="icon"
            className="h-8 w-8"
            onClick={() => setViewMode('list')}
          >
            <List className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="flex flex-col gap-3 mb-4">
        <div className="flex flex-wrap items-center gap-2">
          {/* Search */}
          <div className="relative flex-1 min-w-[180px] max-w-xs">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search patterns..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-9"
            />
          </div>

          {/* Sort */}
          <Select
            value={sortBy}
            onValueChange={(v) => setSortBy(v as SortOption)}
          >
            <SelectTrigger className="w-[140px] h-9">
              {sortDesc ? (
                <SortDesc className="w-4 h-4 mr-2 text-muted-foreground" />
              ) : (
                <SortAsc className="w-4 h-4 mr-2 text-muted-foreground" />
              )}
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="success_rate">Success Rate</SelectItem>
              <SelectItem value="occurrences">Occurrences</SelectItem>
              <SelectItem value="last_triggered">Last Triggered</SelectItem>
            </SelectContent>
          </Select>

          {/* Sort Direction */}
          <Button
            variant="outline"
            size="icon"
            className="h-9 w-9"
            onClick={() => setSortDesc(!sortDesc)}
          >
            {sortDesc ? <SortDesc className="h-4 w-4" /> : <SortAsc className="h-4 w-4" />}
          </Button>
        </div>

        {/* Pattern Type Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
          <button
            type="button"
            onClick={() => setSelectedPatternType('all')}
            className={cn(
              'rounded-full px-3 py-1 text-sm whitespace-nowrap transition-colors',
              selectedPatternType === 'all'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted/50 text-muted-foreground hover:bg-muted'
            )}
          >
            All{' '}
            <span className={cn(selectedPatternType === 'all' ? 'text-primary-foreground/70' : 'text-muted-foreground/70')}>
              ({Object.values(patternTypeCounts).reduce((sum, c) => sum + c, 0)})
            </span>
          </button>
          {(Object.entries(patternTypeConfig) as [PatternType, typeof patternTypeConfig[PatternType]][])
            .filter(([type]) => (patternTypeCounts[type] ?? 0) > 0)
            .map(([type, config]) => (
              <button
                key={type}
                type="button"
                onClick={() => setSelectedPatternType(type)}
                className={cn(
                  'rounded-full px-3 py-1 text-sm whitespace-nowrap transition-colors',
                  selectedPatternType === type
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted/50 text-muted-foreground hover:bg-muted'
                )}
              >
                {config.label}{' '}
                <span className={cn(selectedPatternType === type ? 'text-primary-foreground/70' : 'text-muted-foreground/70')}>
                  ({patternTypeCounts[type]})
                </span>
              </button>
            ))}
        </div>

        {/* Success Rate Slider */}
        <div className="flex items-center gap-3">
          <label className="text-sm text-muted-foreground whitespace-nowrap">
            Min Success Rate:
          </label>
          <input
            type="range"
            min="0"
            max="100"
            value={minSuccessRate}
            onChange={(e) => setMinSuccessRate(Number(e.target.value))}
            className="flex-1 h-2 bg-muted rounded-lg appearance-none cursor-pointer"
          />
          <span className="text-sm font-medium w-12 text-right">{minSuccessRate}%</span>

          {/* Clear Filters */}
          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearFilters}
              className="gap-1 ml-2"
            >
              <X className="h-4 w-4" />
              Clear
            </Button>
          )}
        </div>
      </div>

      {/* Pattern Grid/List */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center h-32">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          </div>
        ) : filteredPatterns.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-muted-foreground">
            <Brain className="w-8 h-8 mb-2" />
            <p>No patterns found</p>
            {hasActiveFilters && (
              <Button variant="link" onClick={handleClearFilters} className="mt-1">
                Clear filters
              </Button>
            )}
          </div>
        ) : (
          <div
            className={cn(
              viewMode === 'grid'
                ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4'
                : 'flex flex-col gap-3'
            )}
          >
            {filteredPatterns.map((pattern) => (
              <PatternCard
                key={pattern.id}
                pattern={pattern}
                onSelect={onPatternSelect ?? (() => {})}
              />
            ))}
          </div>
        )}

        {/* Themes Section */}
        {themes.length > 0 && (
          <Collapsible
            open={isThemesExpanded}
            onOpenChange={setIsThemesExpanded}
            className="mt-6"
          >
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="w-full justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Brain className="w-4 h-4" />
                  <span className="font-semibold">Conversation Themes</span>
                  <Badge variant="secondary">{sortedThemes.length}</Badge>
                </div>
                {isThemesExpanded ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </Button>
            </CollapsibleTrigger>

            <CollapsibleContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {sortedThemes.map((theme) => (
                  <ThemeCard
                    key={theme.id}
                    theme={theme}
                    onSelect={onThemeSelect}
                  />
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </div>
    </div>
  );
}
