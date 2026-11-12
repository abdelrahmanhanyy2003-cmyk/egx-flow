"use client";

import { Activity, BarChart3, Bell, BriefcaseBusiness, CandlestickChart, Fish, History, LayoutGrid, Settings, ServerCog } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/components/ui/primitives";

const ITEMS = [
  { href: "/", icon: CandlestickChart, label: "Terminal (Alt+T)" },
  { href: "/explorer", icon: LayoutGrid, label: "Stock Explorer (Alt+E)" },
  { href: "/whales", icon: Fish, label: "Whale Radar (Alt+W)" },
  { href: "/portfolio", icon: BriefcaseBusiness, label: "Portfolio (Alt+P)" },
  { href: "/market", icon: BarChart3, label: "Market Overview (Alt+M)" },
  { href: "/replay", icon: History, label: "Historical Replay (Alt+R)" },
  { href: "/alerts", icon: Bell, label: "Alerts Center (Alt+A)" },
  { href: "/status", icon: ServerCog, label: "API Connection Status" },
  { href: "/settings", icon: Settings, label: "Settings" },
];

export function NavRail() {
  const path = usePathname();
  return (
    <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-line bg-bg-1 py-2">
      {ITEMS.map(({ href, icon: Icon, label }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} title={label} className={cn("flex h-8 w-8 items-center justify-center rounded-sm", active ? "bg-accent/15 text-accent" : "text-fg-mute hover:bg-bg-3 hover:text-fg")}>
            <Icon size={16} />
          </Link>
        );
      })}
      <div className="mt-auto text-fg-mute" title="Read-only: no order entry">
        <Activity size={14} />
      </div>
    </nav>
  );
}
