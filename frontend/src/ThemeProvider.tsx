import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Moon, Sun } from "lucide-react";
import { applyTheme, PALETTE, readPref, resolvePref, THEME_KEY, type Palette, type ResolvedTheme, type ThemePref } from "./theme";
import { translate } from "./i18n/I18nProvider";

type ThemeCtx = {
  pref: ThemePref;
  resolved: ResolvedTheme;
  palette: Palette;
  setPref: (pref: ThemePref) => void;
};

const Ctx = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(() => (typeof window === "undefined" ? "system" : readPref()));
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolvePref(typeof window === "undefined" ? "system" : readPref()));

  const apply = useCallback((next: ThemePref) => {
    applyTheme(next);
    setResolved(resolvePref(next));
  }, []);

  useEffect(() => {
    apply(pref);
    try { localStorage.setItem(THEME_KEY, pref); } catch { /* private mode */ }
  }, [pref, apply]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => { if (pref === "system") apply(pref); };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [pref, apply]);

  const value = useMemo<ThemeCtx>(() => ({
    pref,
    resolved,
    palette: PALETTE[resolved],
    setPref: setPrefState,
  }), [pref, resolved]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}

/** Palette hex pour les interpolations D3 (re-render au changement de thème). */
export function usePalette(): Palette {
  return useTheme().palette;
}

export function ThemeToggle() {
  const { resolved, setPref } = useTheme();
  const dark = resolved === "dark";
  return (
    <button
      type="button"
      onClick={() => setPref(dark ? "light" : "dark")}
      title={dark ? translate("theme.toLight") : translate("theme.toDark")}
      aria-label={dark ? translate("theme.toLight") : translate("theme.toDark")}
      className="rounded-sm p-1 text-faint transition-colors hover:bg-surface hover:text-ink"
    >
      {dark ? <Sun size={13} strokeWidth={1.75} /> : <Moon size={13} strokeWidth={1.75} />}
    </button>
  );
}
