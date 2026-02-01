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
  Database,
  ChevronDown,
} from 'lucide-react';
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
  DropdownMenuGroup,
} from '@/components/ui/dropdown-menu';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { ThemeToggle } from '@/components/theme-toggle';
import { cn } from '@/lib/utils';
import { useDeepInsights } from '@/lib/hooks/use-deep-insights';

// Primary navigation items - Insight-focused
const primaryNavItems = [
  { href: '/', label: 'Home', icon: Home },
  { href: '/insights', label: 'Insights', icon: Lightbulb },
  { href: '/conversations', label: 'Conversations', icon: MessageSquare },
  { href: '/research', label: 'Research', icon: FlaskConical },
];

// Secondary navigation items - Data views
const secondaryNavItems = [
  { href: '/stocks', label: 'Market Data', icon: BarChart3 },
  { href: '/signals', label: 'Signals', icon: Zap },
];

export function Header() {
  const pathname = usePathname();

  // Fetch insights to show counts
  const { data: insightsData } = useDeepInsights({ limit: 100 });

  // Calculate badge counts
  const pendingModifications = insightsData?.items?.filter(
    (i) => ['STRONG_BUY', 'BUY', 'SELL', 'STRONG_SELL'].includes(i.action)
  ).length || 0;

  const activeResearch = insightsData?.items?.filter(
    (i) => i.action === 'WATCH'
  ).length || 0;

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center w-full px-4 md:px-6">
        {/* Mobile menu */}
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" className="md:hidden mr-2">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Toggle menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72">
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-primary" />
                Market Analyzer
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

                  // Add badges
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

            {/* Secondary Navigation */}
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2 px-3 flex items-center gap-2">
                <Database className="h-3.5 w-3.5" />
                Data
              </h3>
              <nav className="flex flex-col gap-1">
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
            </div>

            <Separator className="my-4" />

            {/* Quick Actions */}
            <div className="flex flex-col gap-2">
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
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <TrendingUp className="h-5 w-5 text-primary" />
          <span className="hidden sm:inline">Market Analyzer</span>
        </Link>

        {/* Desktop nav - Primary items */}
        <nav className="hidden md:flex items-center gap-1 ml-6">
          {primaryNavItems.map((item) => {
            const isActive = pathname === item.href ||
              (item.href !== '/' && pathname.startsWith(item.href));

            // Add badges for desktop
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
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                )}
              >
                {item.label}
                {badge !== null && (
                  <Badge
                    variant={item.label === 'Insights' ? 'destructive' : 'secondary'}
                    className="h-4 min-w-4 px-1 text-[10px]"
                  >
                    {badge}
                  </Badge>
                )}
              </Link>
            );
          })}

          {/* Data dropdown for desktop */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                className={cn(
                  'text-sm font-medium gap-1',
                  secondaryNavItems.some((item) => pathname.startsWith(item.href))
                    ? 'text-foreground'
                    : 'text-muted-foreground'
                )}
              >
                Data
                <ChevronDown className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {secondaryNavItems.map((item) => {
                const Icon = item.icon;
                return (
                  <DropdownMenuItem key={item.href} asChild>
                    <Link href={item.href} className="flex items-center gap-2">
                      <Icon className="h-4 w-4" />
                      {item.label}
                    </Link>
                  </DropdownMenuItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        </nav>

        {/* Spacer to push right-side items to the far right */}
        <div className="flex-1" />

        {/* Right-side controls */}
        <div className="flex items-center gap-2">
          {/* Theme toggle */}
          <ThemeToggle />

          {/* User menu */}
          <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="rounded-full">
              <Avatar className="h-8 w-8">
                <AvatarFallback>U</AvatarFallback>
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
    </header>
  );
}
