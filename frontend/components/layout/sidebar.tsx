'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  Home,
  Lightbulb,
  MessageSquare,
  FlaskConical,
  BarChart3,
  Zap,
  ChevronDown,
  Database,
  Target,
  BookOpen,
  Briefcase,
  FileText,
  Activity,
} from 'lucide-react';
import { useDeepInsights } from '@/lib/hooks/use-deep-insights';

interface SidebarItem {
  name: string;
  href: string;
  icon: React.ReactNode;
  badge?: number;
  badgeVariant?: 'default' | 'secondary' | 'destructive' | 'outline';
}

// Primary navigation - Insight-focused
const primaryNav: SidebarItem[] = [
  { name: 'Home', href: '/', icon: <Home className="h-4 w-4" /> },
  { name: 'Insights', href: '/insights', icon: <Lightbulb className="h-4 w-4" /> },
  { name: 'Patterns', href: '/patterns', icon: <BookOpen className="h-4 w-4" /> },
  { name: 'Track Record', href: '/track-record', icon: <Target className="h-4 w-4" /> },
  { name: 'Reports', href: '/reports', icon: <FileText className="h-4 w-4" /> },
  { name: 'Portfolio', href: '/portfolio', icon: <Briefcase className="h-4 w-4" /> },
  { name: 'Conversations', href: '/conversations', icon: <MessageSquare className="h-4 w-4" /> },
  { name: 'Research', href: '/research', icon: <FlaskConical className="h-4 w-4" /> },
];

// Secondary navigation - Supporting data views
const secondaryNav: SidebarItem[] = [
  { name: 'Market Data', href: '/stocks', icon: <BarChart3 className="h-4 w-4" /> },
  { name: 'Signals', href: '/signals', icon: <Zap className="h-4 w-4" /> },
  { name: 'Past Runs', href: '/runs', icon: <Activity className="h-4 w-4" /> },
];

function isActiveLink(pathname: string, href: string): boolean {
  if (href === '/') {
    return pathname === '/';
  }
  return pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  const [dataExpanded, setDataExpanded] = useState(false);

  // Fetch insights to show counts
  const { data: insightsData } = useDeepInsights({ limit: 100 });

  // Calculate badge counts
  const pendingModifications = insightsData?.items?.filter(
    (i) => ['STRONG_BUY', 'BUY', 'SELL', 'STRONG_SELL'].includes(i.action)
  ).length || 0;

  const activeResearch = insightsData?.items?.filter(
    (i) => i.action === 'WATCH'
  ).length || 0;

  // Create primary nav with dynamic badges
  const primaryNavWithBadges = primaryNav.map((item) => {
    if (item.name === 'Insights' && pendingModifications > 0) {
      return { ...item, badge: pendingModifications, badgeVariant: 'destructive' as const };
    }
    if (item.name === 'Research' && activeResearch > 0) {
      return { ...item, badge: activeResearch, badgeVariant: 'secondary' as const };
    }
    return item;
  });

  return (
    <aside className="hidden md:flex w-64 flex-col border-r bg-background sticky top-12 h-[calc(100vh-3rem)] overflow-y-auto">
      {/* Primary Navigation - Insight-focused */}
      <div className="flex flex-col gap-2 p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">
          Insights
        </h2>
        <nav className="flex flex-col gap-1">
          {primaryNavWithBadges.map((item) => {
            const isActive = isActiveLink(pathname, item.href);
            return (
              <Button
                key={item.href}
                variant={isActive ? 'secondary' : 'ghost'}
                className={cn(
                  'justify-start gap-2',
                  isActive && 'bg-secondary font-medium'
                )}
                asChild
              >
                <Link href={item.href}>
                  {item.icon}
                  <span className="flex-1">{item.name}</span>
                  {item.badge !== undefined && item.badge > 0 && (
                    <Badge
                      variant={item.badgeVariant || 'secondary'}
                      className="ml-auto h-5 min-w-5 px-1.5"
                    >
                      {item.badge}
                    </Badge>
                  )}
                </Link>
              </Button>
            );
          })}
        </nav>
      </div>

      <Separator />

      {/* Secondary Navigation - Collapsible Data section */}
      <div className="flex flex-col gap-2 p-4">
        <Collapsible open={dataExpanded} onOpenChange={setDataExpanded}>
          <CollapsibleTrigger asChild>
            <Button
              variant="ghost"
              className="w-full justify-between px-2 py-1.5 h-auto text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground"
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
              {secondaryNav.map((item) => {
                const isActive = isActiveLink(pathname, item.href);
                return (
                  <Button
                    key={item.href}
                    variant={isActive ? 'secondary' : 'ghost'}
                    className={cn(
                      'justify-start gap-2 text-muted-foreground hover:text-foreground',
                      isActive && 'bg-secondary text-foreground'
                    )}
                    asChild
                  >
                    <Link href={item.href}>
                      {item.icon}
                      {item.name}
                    </Link>
                  </Button>
                );
              })}
            </nav>
          </CollapsibleContent>
        </Collapsible>
      </div>

    </aside>
  );
}
