"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ws } from "@/lib/ws";
import { useUi } from "@/store/ui";
import type { AlertItem } from "@/lib/types";
import { TopBar } from "./TopBar";
import { NavRail } from "./NavRail";
import { AlertToaster, playAlertSound } from "./AlertToaster";
import { SymbolSearch } from "./SymbolSearch";
import { ShortcutsDialog } from "./ShortcutsDialog";

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pushAlert = useUi((s) => s.pushAlert);

  useEffect(() => {
    ws.connect();
    return ws.onGlobal((msg) => {
      if (msg.type === "alert") {
        const a = msg.data as AlertItem;
        pushAlert(a);
        if (a.sound !== false && useUi.getState().sound) playAlertSound(a.severity);
      }
    });
  }, [pushAlert]);

  // global keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      const typing = tgt && (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT" || tgt.isContentEditable);
      const ui = useUi.getState();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ui.setSearchOpen(true);
        return;
      }
      if (typing) return;
      if (e.key === "/") {
        e.preventDefault();
        ui.setSearchOpen(true);
      } else if (e.key === "?") ui.setShortcutsOpen(!ui.shortcutsOpen);
      else if (e.altKey && e.key.toLowerCase() === "a") router.push("/alerts");
      else if (e.altKey && e.key.toLowerCase() === "w") router.push("/whales");
      else if (e.altKey && e.key.toLowerCase() === "p") router.push("/portfolio");
      else if (e.altKey && e.key.toLowerCase() === "t") router.push("/");
      else if (e.altKey && e.key.toLowerCase() === "m") router.push("/market");
      else if (e.altKey && e.key.toLowerCase() === "e") router.push("/explorer");
      else if (e.altKey && e.key.toLowerCase() === "r") router.push("/replay");
      else if (e.key === "Escape") {
        ui.setSearchOpen(false);
        ui.setShortcutsOpen(false);
        ui.setDrawTool("none");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  // Client-only workstation: live clocks, persisted layout and canvases make SSR
  // output inherently different from the first client render.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="flex h-screen items-center justify-center text-fg-mute">Loading EGX Flow…</div>;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <NavRail />
        <main className="min-h-0 min-w-0 flex-1">{children}</main>
      </div>
      <AlertToaster />
      <SymbolSearch />
      <ShortcutsDialog />
    </div>
  );
}
