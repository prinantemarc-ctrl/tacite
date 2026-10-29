import { ReactNode, useEffect, useRef, useState } from "react";
import { T } from "../../theme";

/** Largeur du conteneur, suivie par ResizeObserver. */
export function useWidth<T extends HTMLElement>(fallback = 800): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw) setW(cw);
    });
    ro.observe(ref.current);
    setW(ref.current.clientWidth || fallback);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export type Tip = { x: number; y: number; content: ReactNode } | null;

export function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div
      className="pointer-events-none absolute z-20 max-w-[260px] rounded-sm border border-hair bg-paper px-2.5 py-1.5 text-[11.5px] leading-snug text-ink shadow-[0_8px_24px_-12px_rgba(0,0,0,.25)]"
      style={{ left: tip.x + 12, top: tip.y + 12 }}
    >
      {tip.content}
    </div>
  );
}

/** Styles de blocs dans la palette close : on distingue par remplissage et trait, pas par teinte. */
export const CLUSTER_STYLES = [
  { fill: T.accent, stroke: T.accent, dash: "" },
  { fill: T.ink, stroke: T.ink, dash: "" },
  { fill: T.paper, stroke: T.accent, dash: "" },
  { fill: T.paper, stroke: T.ink, dash: "" },
  { fill: T.muted, stroke: T.muted, dash: "" },
  { fill: T.paper, stroke: T.muted, dash: "3 2" },
];
export const clusterStyle = (i: number | null | undefined) =>
  i === null || i === undefined ? { fill: T.faint, stroke: T.faint, dash: "" } : CLUSTER_STYLES[i % CLUSTER_STYLES.length];

export function Legend({ items }: { items: { swatch: ReactNode; label: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">{it.swatch}{it.label}</span>
      ))}
    </div>
  );
}

export function Swatch({ fill, stroke, dash, r = 5 }: { fill: string; stroke: string; dash?: string; r?: number }) {
  return (
    <svg width={r * 2 + 2} height={r * 2 + 2}>
      <circle cx={r + 1} cy={r + 1} r={r} fill={fill} stroke={stroke} strokeWidth={1.25} strokeDasharray={dash || undefined} />
    </svg>
  );
}

export const fmt = (n: number, d = 2) => (n > 0 ? "+" : "") + n.toFixed(d);
