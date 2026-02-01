'use client';

import { useState, useMemo } from 'react';
import {
  BookOpen, Brain, ChevronDown, ChevronUp, Search, Grid, List,
  TrendingUp, Zap, RefreshCcw, Calendar, BarChart3, Target,
  CircleSlash, Filter, SortAsc, SortDesc, X
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
const patternTypeConfig: Record<PatternType, { color: string; icon: typeof TrendingUp; label: string }> = {
  TECHNICAL_SETUP: { color: 'bg-blue-500', icon: TrendingUp, label: 'Technical Setup' },
  MACRO_CORRELATION: { color: 'bg-purple-500', icon: RefreshCcw, label: 'Macro Correlation' },
  SECTOR_ROTATION: { color: 'bg-green-500', icon: Zap, label: 'Sector Rotation' },
  EARNINGS_PATTERN: { color: 'bg-amber-500', icon: Calendar, label: 'Earnings Pattern' },
  SEASONALITY: { color: 'bg-cyan-500', icon: BarChart3, label: 'Seasonality' },
  CROSS_ASSET: { color: 'bg-pink-500', icon: Target, label: 'Cross Asset' },
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
 * Pattern card component
 */
function PatternCard({
  pattern,
  isExpanded,
  onToggleExpand,
  onSelect,
}: {
  pattern: KnowledgePattern;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onSelect?: (pattern: KnowledgePattern) => void;
}) {
  const typeConfig = patternTypeConfig[pattern.pattern_type];
  const TypeIcon = typeConfig.icon;

  return (
    <Card
      className={cn(
        'hover:shadow-md transition-shadow cursor-pointer',
        !pattern.is_active && 'opacity-60'
      )}
      onClick={() => onSelect?.(pattern)}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            {/* Type Badge */}
            <Badge className={`${typeConfig.color} text-white mb-2`}>
              <TypeIcon className="w-3 h-3 mr-1" />
              {typeConfig.label}
            </Badge>

            {/* Pattern Name */}
            <CardTitle className="text-base font-semibold line-clamp-2">
              {pattern.pattern_name}
            </CardTitle>

            {/* Description (truncated) */}
            <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
              {pattern.description}
            </p>
          </div>

          {/* Success Rate Ring */}
          <SuccessRateRing rate={pattern.success_rate} />
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {/* Stats Row */}
        <div className="flex items-center gap-4 text-sm text-muted-foreground mb-2">
          <div className="flex items-center gap-1">
            <BarChart3 className="w-3.5 h-3.5" />
            <span>{pattern.occurrences} triggers</span>
          </div>
          {pattern.last_triggered_at && (
            <div className="flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5" />
              <span>{formatRelativeTime(pattern.last_triggered_at)}</span>
            </div>
          )}
          {!pattern.is_active && (
            <div className="flex items-center gap-1 text-yellow-600">
              <CircleSlash className="w-3.5 h-3.5" />
              <span>Inactive</span>
            </div>
          )}
        </div>

        {/* Expand/Collapse Details */}
        <Collapsible open={isExpanded} onOpenChange={onToggleExpand}>
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="w-full mt-2"
              onClick={(e) => {
                e.stopPropagation();
                onToggleExpand();
              }}
            >
              {isExpanded ? (
                <>Less Details <ChevronUp className="ml-1 w-4 h-4" /></>
              ) : (
                <>More Details <ChevronDown className="ml-1 w-4 h-4" /></>
              )}
            </Button>
          </CollapsibleTrigger>

          <CollapsibleContent className="space-y-4 pt-4" onClick={(e) => e.stopPropagation()}>
            {/* Full Description */}
            <div>
              <h4 className="text-sm font-semibold mb-1">Description</h4>
              <p className="text-sm text-muted-foreground">{pattern.description}</p>
            </div>

            {/* Trigger Conditions */}
            {Object.keys(pattern.trigger_conditions).length > 0 && (
              <div>
                <h4 className="text-sm font-semibold mb-1">Trigger Conditions</h4>
                <ul className="text-sm text-muted-foreground list-disc list-inside">
                  {formatTriggerConditions(pattern.trigger_conditions).map((condition, i) => (
                    <li key={i}>{condition}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Expected Outcome */}
            <div>
              <h4 className="text-sm font-semibold mb-1">Expected Outcome</h4>
              <p className="text-sm text-muted-foreground">{pattern.expected_outcome}</p>
            </div>

            {/* Success Stats */}
            <div className="grid grid-cols-2 gap-4 bg-muted/50 rounded-lg p-3">
              <div>
                <div className="text-xs text-muted-foreground">Success Rate</div>
                <div className="text-lg font-bold">
                  {pattern.successful_outcomes}/{pattern.occurrences}
                </div>
              </div>
              {pattern.avg_return_when_triggered !== undefined && (
                <div>
                  <div className="text-xs text-muted-foreground">Avg Return</div>
                  <div className={cn(
                    'text-lg font-bold',
                    pattern.avg_return_when_triggered >= 0 ? 'text-green-600' : 'text-red-600'
                  )}>
                    {pattern.avg_return_when_triggered >= 0 ? '+' : ''}
                    {(pattern.avg_return_when_triggered * 100).toFixed(2)}%
                  </div>
                </div>
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
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
  const [expandedPatternId, setExpandedPatternId] = useState<string | null>(null);

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

          {/* Pattern Type */}
          <Select
            value={selectedPatternType}
            onValueChange={(v) => setSelectedPatternType(v as PatternType | 'all')}
          >
            <SelectTrigger className="w-[160px] h-9">
              <Filter className="w-4 h-4 mr-2 text-muted-foreground" />
              <SelectValue placeholder="Pattern Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {Object.entries(patternTypeConfig).map(([type, config]) => (
                <SelectItem key={type} value={type}>
                  {config.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

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
                isExpanded={expandedPatternId === pattern.id}
                onToggleExpand={() =>
                  setExpandedPatternId(expandedPatternId === pattern.id ? null : pattern.id)
                }
                onSelect={onPatternSelect}
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
