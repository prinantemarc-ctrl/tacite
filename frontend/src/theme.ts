/** Tokens du kit. Les utilitaires Tailwind lisent les CSS variables ; Recharts aussi.
 *  D3 ne sait pas interpoler `var()` / oklch : les échelles utilisent `PALETTE`. */

export type ThemePref = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_KEY = "tacite-theme";

export type Palette = {
  paper: string;
  ink: string;
  muted: string;
  faint: string;
  accent: string;
  accentStrong: string;
  hair: string;
  hairSoft: string;
  surface: string;
  tint: string;
  confidential: string;
};

export const PALETTE: Record<ResolvedTheme, Palette> = {
  light: {
    paper: "#ffffff",
    ink: "#1c1c1c",
    muted: "#6b6b6b",
    faint: "#9a9a9a",
    accent: "#6e6230",
    accentStrong: "#5a5027",
    hair: "#e3e3e3",
    hairSoft: "#eeeeee",
    surface: "#f2f2f2",
    tint: "#f3f1ea",
    confidential: "#8a2e2a",
  },
  dark: {
    paper: "#1a1916",
    ink: "#eeece6",
    muted: "#a8a396",
    faint: "#7d786e",
    accent: "#c4ae62",
    accentStrong: "#d4c07a",
    hair: "#322f2a",
    hairSoft: "#282622",
    surface: "#22211e",
    tint: "#2a271c",
    confidential: "#c45c56",
  },
};

/** Valeurs live via CSS — suivent le thème sans re-render. */
export const T = {
  paper: "var(--color-paper)",
  ink: "var(--color-ink)",
  muted: "var(--color-muted)",
  faint: "var(--color-faint)",
  accent: "var(--color-accent)",
  accentStrong: "var(--color-accent-strong)",
  hair: "var(--color-hair)",
  hairSoft: "var(--color-hair-soft)",
  surface: "var(--color-surface)",
  tint: "var(--color-tint)",
  confidential: "var(--color-confidential)",
};

export const CHART_FONT = "Geist, -apple-system, sans-serif";

export const tooltipStyle = {
  backgroundColor: T.paper,
  border: `1px solid ${T.hair}`,
  borderRadius: 3,
  fontSize: 11.5,
  fontFamily: CHART_FONT,
  color: T.ink,
  boxShadow: "0 8px 24px -12px rgba(0,0,0,.2)",
  padding: "6px 10px",
};

export const axisTick = { fill: T.muted, fontSize: 10.5, fontFamily: CHART_FONT };

/** Quatre séries max, toutes dans la palette. */
export const SERIES = [T.ink, T.accent, T.muted, T.faint];

export function readPref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch { /* private mode */ }
  return "system";
}

export function systemDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolvePref(pref: ThemePref): ResolvedTheme {
  if (pref === "system") return systemDark() ? "dark" : "light";
  return pref;
}

export function applyTheme(pref: ThemePref) {
  const resolved = resolvePref(pref);
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", PALETTE[resolved].paper);
}
