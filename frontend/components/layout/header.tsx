'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Menu,
  TrendingUp,
  Home,
  Lightbulb,
  MessageSquare,
  FlaskConical,
  BarChart3,
  Zap,
  Settings,
  Play,
  Target,
  BookOpen,
  Briefcase,
  FileText,
  Database,
  ChevronDown,
} from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Separator } from '@/components/ui/separator';
import { ThemeToggle } from '@/components/theme-toggle';
import { cn } from '@/lib/utils';
import { useDeepInsights } from '@/lib/hooks/use-deep-insights';

// Mirror sidebar navigation for mobile menu
const primaryNavItems = [
  { href: '/', label: 'Home', icon: Home },
  { href: '/insights', label: 'Insights', icon: Lightbulb },
  { href: '/patterns', label: 'Patterns', icon: BookOpen },
  { href: '/track-record', label: 'Track Record', icon: Target },
  { href: '/reports', label: 'Reports', icon: FileText },
  { href: '/portfolio', label: 'Portfolio', icon: Briefcase },
  { href: '/conversations', label: 'Conversations', icon: MessageSquare },
  { href: '/research', label: 'Research', icon: FlaskConical },
];

const secondaryNavItems = [
  { href: '/stocks', label: 'Market Data', icon: BarChart3 },
  { href: '/signals', label: 'Signals', icon: Zap },
];

export function Header() {
  const pathname = usePathname();
  const [dataExpanded, setDataExpanded] = useState(false);

  // Fetch insights for mobile menu badges
  const { data: insightsData } = useDeepInsights({ limit: 100 });

  const pendingModifications = insightsData?.items?.filter(
    (i) => ['STRONG_BUY', 'BUY', 'SELL', 'STRONG_SELL'].includes(i.action)
  ).length || 0;

  const activeResearch = insightsData?.items?.filter(
    (i) => i.action === 'WATCH'
  ).length || 0;

  return (
    <header className="sticky top-0 z-50 w-full bg-gradient-to-r from-slate-50 via-indigo-50 to-slate-50 dark:from-slate-950 dark:via-purple-950 dark:to-slate-950 border-b border-slate-200 dark:border-transparent">
      <div className="flex h-12 items-center w-full px-4 md:px-6">
        {/* Mobile menu */}
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="md:hidden mr-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-white/80 dark:hover:text-white dark:hover:bg-white/10">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Toggle menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72">
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-purple-500" />
                Teletraan
              </SheetTitle>
            </SheetHeader>

            {/* Primary Navigation */}
            <div className="mt-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 px-3">
                Insights
              </h3>
              <nav className="flex flex-col gap-1">
                {primaryNavItems.map((item) => {
                  const Icon = item.icon;
                  const isActive = pathname === item.href ||
                    (item.href !== '/' && pathname.startsWith(item.href));
                  const badge = item.label === 'Insights' && pendingModifications > 0
                    ? pendingModifications
                    : item.label === 'Research' && activeResearch > 0
                    ? activeResearch
                    : null;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={cn(
                        'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary text-primary-foreground'
                          : 'hover:bg-muted'
                      )}
                    >
                      <Icon className="h-4 w-4" />
                      <span className="flex-1">{item.label}</span>
                      {badge !== null && (
                        <Badge
                          variant={item.label === 'Insights' ? 'destructive' : 'secondary'}
                          className="h-5 min-w-5 px-1.5"
                        >
                          {badge}
                        </Badge>
                      )}
                    </Link>
                  );
                })}
              </nav>
            </div>

            <Separator className="my-4" />

            {/* Secondary Navigation - Collapsible */}
            <Collapsible open={dataExpanded} onOpenChange={setDataExpanded}>
              <CollapsibleTrigger asChild>
                <Button
                  variant="ghost"
                  className="w-full justify-between px-3 py-1.5 h-auto text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
                >
                  <span className="flex items-center gap-2">
                    <Database className="h-3.5 w-3.5" />
                    Data
                  </span>
                  <ChevronDown
                    className={cn(
                      'h-3.5 w-3.5 transition-transform duration-200',
                      dataExpanded && 'rotate-180'
                    )}
                  />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <nav className="flex flex-col gap-1 mt-2">
                  {secondaryNavItems.map((item) => {
                    const Icon = item.icon;
                    const isActive = pathname.startsWith(item.href);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={cn(
                          'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors text-muted-foreground',
                          isActive
                            ? 'bg-secondary text-foreground'
                            : 'hover:bg-muted hover:text-foreground'
                        )}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </Link>
                    );
                  })}
                </nav>
              </CollapsibleContent>
            </Collapsible>

            <Separator className="my-4" />

            {/* Bottom actions */}
            <div className="flex flex-col gap-2">
              <Button variant="default" className="w-full justify-center gap-2" asChild>
                <Link href="/analysis/run">
                  <Play className="h-4 w-4" />
                  Run Analysis
                </Link>
              </Button>
              <Link
                href="/settings"
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  pathname === '/settings'
                    ? 'bg-secondary text-foreground'
                    : 'hover:bg-muted text-muted-foreground'
                )}
              >
                <Settings className="h-4 w-4" />
                Settings
              </Link>
            </div>
          </SheetContent>
        </Sheet>

        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 font-semibold group">
          <TrendingUp className="h-5 w-5 text-indigo-500 dark:text-cyan-400 dark:drop-shadow-[0_0_6px_rgba(34,211,238,0.4)] dark:group-hover:drop-shadow-[0_0_10px_rgba(34,211,238,0.6)] transition-all" />
          <span className="hidden sm:inline bg-gradient-to-r from-indigo-600 to-purple-600 dark:from-cyan-300 dark:to-purple-300 bg-clip-text text-transparent font-bold tracking-tight text-base dark:drop-shadow-[0_0_8px_rgba(168,85,247,0.3)]">
            Teletraan
          </span>
        </Link>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Right-side controls */}
        <div className="flex items-center gap-1">
          {/* Theme toggle */}
          <ThemeToggle variant="header" />

          {/* User menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="rounded-full hover:bg-slate-100 dark:hover:bg-white/10">
                <Avatar className="h-7 w-7 ring-1 ring-slate-200 dark:ring-white/20">
                  <AvatarFallback className="bg-gradient-to-br from-indigo-500 to-purple-500 dark:from-cyan-500 dark:to-purple-500 text-white text-xs font-medium">
                    U
                  </AvatarFallback>
                </Avatar>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>My Account</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link href="/settings">Settings</Link>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      {/* Bottom accent line */}
      <div className="h-[2px] bg-gradient-to-r from-indigo-200 via-purple-200 to-pink-200 opacity-60 dark:from-cyan-500 dark:via-purple-500 dark:to-pink-500 dark:opacity-80" />
    </header>
  );
}
