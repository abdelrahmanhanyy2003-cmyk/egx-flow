"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { cn } from "./primitives";

export interface Col<T> {
  key: string;
  label: ReactNode;
  value?: (r: T) => number | string | null | undefined;
  render?: (r: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
  title?: string;
}

export function DataTable<T>({
  rows,
  cols,
  rowKey,
  initialSort,
  search,
  searchKeys,
  onRowClick,
  maxRows,
  empty = "No rows",
  dense = true,
}: {
  rows: T[];
  cols: Col<T>[];
  rowKey: (r: T, i: number) => string;
  initialSort?: { key: string; dir: "asc" | "desc" };
  search?: boolean;
  searchKeys?: ((r: T) => string)[];
  onRowClick?: (r: T) => void;
  maxRows?: number;
  empty?: ReactNode;
  dense?: boolean;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const [q, setQ] = useState("");
  const out = useMemo(() => {
    let r = rows;
    const s = q.trim().toLowerCase();
    if (s && searchKeys) r = r.filter((x) => searchKeys.some((k) => k(x).toLowerCase().includes(s)));
    if (sort) {
      const c = cols.find((c) => c.key === sort.key);
      const get = c?.value ?? ((x: T) => (x as any)[sort.key]);
      r = [...r].sort((a, b) => {
        const va = get(a);
        const vb = get(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        const d = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
        return sort.dir === "asc" ? d : -d;
      });
    }
    return maxRows ? r.slice(0, maxRows) : r;
  }, [rows, q, sort, cols, searchKeys, maxRows]);
  return (
    <div className="flex h-full min-h-0 flex-col">
      {search && (
        <div className="border-b border-line p-1">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="h-6 w-full text-[11px]" />
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className={cn("num w-full text-[11px]", dense && "dense")}>
          <thead>
            <tr>
              {cols.map((c) => (
                <th
                  key={c.key}
                  title={c.title}
                  className={cn("cursor-pointer select-none whitespace-nowrap", c.align === "right" && "text-right")}
                  onClick={() => setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === "asc" ? "desc" : "asc" } : { key: c.key, dir: "desc" }))}
                >
                  <span className="inline-flex items-center gap-0.5">
                    {c.label}
                    {sort?.key === c.key && (sort.dir === "asc" ? <ArrowUp size={9} /> : <ArrowDown size={9} />)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {out.map((r, i) => (
              <tr key={rowKey(r, i)} onClick={onRowClick ? () => onRowClick(r) : undefined} className={onRowClick ? "cursor-pointer" : ""}>
                {cols.map((c) => (
                  <td key={c.key} className={cn(c.align === "right" && "text-right", c.className)}>
                    {c.render ? c.render(r) : String(c.value ? c.value(r) ?? "—" : (r as any)[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!out.length && <div className="p-3 text-center text-[11px] text-fg-mute">{empty}</div>}
      </div>
    </div>
  );
}
