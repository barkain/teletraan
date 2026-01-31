'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import {
  LayoutDashboard,
  BarChart3,
  Lightbulb,
  MessageSquare,
} from 'lucide-react';
import { useWatchlist } from '@/lib/hooks/use-watchlist';

interface SidebarItem {
  name: string;
  href: string;
  icon: React.ReactNode;
}

const mainNav: SidebarItem[] = [
  { name: 'Dashboard', href: '/', icon: <LayoutDashboard className="h-4 w-4" /> },
  { name: 'Stocks', href: '/stocks', icon: <BarChart3 className="h-4 w-4" /> },
  { name: 'Insights', href: '/insights', icon: <Lightbulb className="h-4 w-4" /> },
  { name: 'Chat', href: '/chat', icon: <MessageSquare className="h-4 w-4" /> },
];

function isActiveLink(pathname: string, href: string): boolean {
  if (href === '/') {
    return pathname === '/';
  }
  return pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  const { data: watchlist } = useWatchlist();

  // Convert watchlist symbols to sidebar items
  const watchlistItems = (watchlist?.symbols || []).map((symbol) => ({
    name: symbol,
    href: `/stocks/${symbol}`,
  }));

  return (
    <aside className="hidden md:flex w-64 flex-col border-r bg-background">
      <div className="flex flex-col gap-2 p-4">
        <h2 className="text-lg font-semibold tracking-tight">Navigation</h2>
        <nav className="flex flex-col gap-1">
          {mainNav.map((item) => {
            const isActive = isActiveLink(pathname, item.href);
            return (
              <Button
                key={item.href}
                variant={isActive ? 'secondary' : 'ghost'}
                className={cn(
                  'justify-start gap-2',
                  isActive && 'bg-secondary'
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
      </div>

      <Separator />

      <div className="flex flex-col gap-2 p-4">
        <h2 className="text-lg font-semibold tracking-tight">Watchlist</h2>
        <nav className="flex flex-col gap-1">
          {watchlistItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Button
                key={item.href}
                variant={isActive ? 'secondary' : 'ghost'}
                className={cn(
                  'justify-start font-mono',
                  isActive && 'bg-secondary'
                )}
                asChild
              >
                <Link href={item.href}>{item.name}</Link>
              </Button>
            );
          })}
        </nav>
      </div>
    </aside>
  );
}
