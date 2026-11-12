"use client";

import { useUi } from "@/store/ui";

export const SHORTCUTS: [string, string][] = [
  ["Ctrl+K  or  /", "Search symbol"],
  ["Alt+← / Alt+→", "Previous / next symbol tab"],
  ["1 … 9", "Switch to symbol tab N (terminal)"],
  ["+ / -", "Zoom time axis in / out"],
  ["Shift + / Shift -", "Zoom price axis"],
  ["Mouse wheel", "Zoom time · over price axis or with Shift: zoom price"],
  ["Drag", "Pan time & price · drag on price axis: zoom price"],
  ["F  or double-click", "Follow live / reset view"],
  ["H", "Toggle heatmap"],
  ["B", "Toggle volume bubbles (dots)"],
  ["P", "Toggle volume profile"],
  ["V", "Toggle VWAP"],
  ["L", "Horizontal line tool (right-click a line to delete)"],
  ["Ctrl+1 … Ctrl+4", "Switch saved layout 1-4"],
  ["[ / ]", "Collapse left / right sidebar"],
  ["\\", "Collapse bottom panel"],
  ["Alt+T / E / W / P / M / R / A", "Terminal / Explorer / Whale Radar / Portfolio / Market / Replay / Alerts"],
  ["?", "Show this help"],
  ["Esc", "Close dialogs / cancel tool"],
];

export function ShortcutsDialog() {
  const open = useUi((s) => s.shortcutsOpen);
  const setOpen = useUi((s) => s.setShortcutsOpen);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setOpen(false)}>
      <div className="w-[520px] border border-line-2 bg-bg-2 p-4" onClick={(e) => e.stopPropagation()}>
        <div className="panel-title mb-2">Keyboard shortcuts</div>
        <table className="w-full text-[12px]">
          <tbody>
            {SHORTCUTS.map(([k, d]) => (
              <tr key={k} className="border-t border-line">
                <td className="num py-1 pr-4 text-accent">{k}</td>
                <td className="py-1 text-fg-dim">{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
