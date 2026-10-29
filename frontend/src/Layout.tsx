import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Newspaper, Users, Briefcase, FileText, Settings, Map, BookOpen, Sparkles, FileOutput, Layers, X, Plus, Maximize2, LogOut,
} from "lucide-react";
import Chat from "./components/chat/Chat";
import { ChatErrorBoundary } from "./components";
import { TaciteMark } from "./components/TaciteMark";
import { ThemeToggle } from "./ThemeProvider";
import { LanguageToggle, useI18n } from "./i18n/I18nProvider";
import { logout, me, setToken } from "./api";
import DesktopShell from "./DesktopShell";
import { isDesktop } from "./desktop";

const NAV = [
  { to: "/", labelKey: "nav.dashboard", kindKey: "nav.kDashboard", icon: LayoutDashboard },
  { to: "/assistant", labelKey: "nav.assistant", kindKey: "nav.kAssistant", icon: Sparkles },
  { to: "/outlets", labelKey: "nav.outlets", kindKey: "nav.kOutlets", icon: Newspaper },
  { to: "/journalists", labelKey: "nav.journalists", kindKey: "nav.kJournalists", icon: Users },
  { to: "/cartography", labelKey: "nav.cartography", kindKey: "nav.kCartography", icon: Map },
  { to: "/topics", labelKey: "nav.topics", kindKey: "nav.kTopics", icon: Layers },
  { to: "/articles", labelKey: "nav.articles", kindKey: "nav.kArticles", icon: FileText },
  { to: "/clients", labelKey: "nav.clients", kindKey: "nav.kClients", icon: Briefcase },
  { to: "/reports", labelKey: "nav.reports", kindKey: "nav.kReports", icon: FileOutput },
  { to: "/settings", labelKey: "nav.settings", kindKey: "nav.kSettings", icon: Settings },
  { to: "/method", labelKey: "nav.method", kindKey: "nav.kMethod", icon: BookOpen },
];

export default function Layout() {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const current = NAV.find((n) => (n.to === "/" ? pathname === "/" : pathname.startsWith(n.to)));
  const fullBleed = pathname.startsWith("/assistant");
  const [drawer, setDrawer] = useState(false);
  const [pageContext, setPageContext] = useState<{ page: string; label: string } | null>(null);
  const [account, setAccount] = useState("");

  useEffect(() => { me().then((u) => setAccount(u.username)).catch(() => {}); }, []);

  // ⌘K / Ctrl+K ouvre l'assistant avec le contexte de la page courante (titre h1 de la page)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (!fullBleed) setDrawer((d) => !d); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullBleed]);
  useEffect(() => {
    const t = setTimeout(() => {
      const detail = /^\/(outlets|journalists|clients)\/\d+/.test(pathname);
      const h1 = document.querySelector("main h1")?.textContent?.trim();
      setPageContext(detail && h1 ? { page: pathname, label: h1 } : null);
    }, 600);
    return () => clearTimeout(t);
  }, [pathname]);

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <DesktopShell />
      {/* Colonne de navigation */}
      <aside className="flex w-[216px] shrink-0 flex-col border-r border-hair bg-paper">
        {/* Masthead : filet bronze + cartouche outil (cover__masthead du kit) */}
        <div className="px-6 pb-5 pt-7">
          <TaciteMark framed size={40} className="overflow-hidden rounded-[9px] ring-1 ring-hair" />
          <div className="mt-3 h-[2px] w-[52px] bg-accent" />
          <div className="mt-3 text-[12px] font-bold uppercase tracking-tool text-ink">Tacite</div>
          <div className="mt-1 text-[10.5px] text-faint">{t("brand.press")}</div>
        </div>

        <nav className="flex-1 px-3">
          <div className="label mb-2 px-3 text-faint">{t("brand.sections")}</div>
          <ol className="space-y-px">
            {NAV.map((n, i) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end={n.to === "/"}
                  className={({ isActive }) =>
                    `group flex items-center gap-2.5 rounded-sm border-l-[2px] py-[7px] pl-3 pr-2 text-[12.5px] transition-colors ${
                      isActive
                        ? "border-accent bg-tint font-semibold text-ink"
                        : "border-transparent text-muted hover:bg-surface hover:text-ink"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span className={`num w-4 text-[9.5px] font-bold tracking-[0.08em] ${isActive ? "text-accent" : "text-faint"}`}>
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <n.icon size={14} strokeWidth={1.75} className={isActive ? "text-accent-strong" : "text-faint group-hover:text-muted"} />
                      {t(n.labelKey)}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ol>
        </nav>

        <div className="flex items-center justify-between gap-2 border-t border-hair px-4 py-3">
          <span className="min-w-0 truncate text-[11px] text-muted" title={account}>{account}</span>
          <button
            type="button"
            title={t("auth.logout")}
            onClick={() => { logout().catch(() => {}).finally(() => { setToken(""); window.location.assign("/login"); }); }}
            className="rounded-sm p-1 text-faint hover:bg-surface hover:text-ink"
          >
            <LogOut size={14} />
          </button>
        </div>
      </aside>

      {/* Corps */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Bandeau courant (stamp__head du kit) */}
        <div className="flex items-center justify-between border-b border-hair px-8 py-2.5 text-[9.5px] leading-none">
          <span className="flex items-center gap-2 font-bold uppercase tracking-[0.3em] text-accent-strong">
            <TaciteMark framed size={18} className="overflow-hidden rounded-[4px] ring-1 ring-hair" />
            Tacite
          </span>
          <div className="flex items-center gap-3">
            {isDesktop() && <span className="uppercase tracking-[0.16em] text-accent">Bureau</span>}
            <span className="uppercase tracking-[0.16em] text-faint">{current ? t(current.kindKey) : t("brand.report")}</span>
            <LanguageToggle />
            <ThemeToggle />
          </div>
        </div>
        {fullBleed ? (
          <main className="flex min-h-0 flex-1 flex-col overflow-hidden"><Outlet /></main>
        ) : (
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[1180px] px-8 pb-16 pt-7">
              <Outlet />
            </div>
          </main>
        )}
      </div>

      {/* Assistant en panneau latéral (⌘K), avec le contexte de la page */}
      {!fullBleed && (
        <button onClick={() => setDrawer(true)} title={t("assistant.fab")}
          className="fixed bottom-6 right-6 z-30 flex h-10 items-center gap-2 rounded-pill border border-accent bg-paper px-3.5 text-[12px] font-semibold text-accent-strong shadow-[0_8px_24px_-12px_rgba(0,0,0,.3)] transition-colors hover:bg-tint">
          <Sparkles size={14} /> {t("nav.assistant")} <kbd className="rounded-[2px] border border-hair px-1 text-[9.5px] font-normal text-faint">⌘K</kbd>
        </button>
      )}
      {drawer && <AssistantDrawer context={pageContext} onClose={() => setDrawer(false)} />}
    </div>
  );
}

function AssistantDrawer({ context, onClose }: { context: { page: string; label: string } | null; onClose: () => void }) {
  const { t } = useI18n();
  const [cid, setCid] = useState<number | null>(null);
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="fixed inset-0 z-40 bg-ink/20" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-[520px] max-w-full flex-col border-l border-hair bg-paper shadow-[-16px_0_48px_-24px_rgba(0,0,0,.35)]">
        <div className="flex items-center justify-between border-b border-hair px-4 py-3">
          <div className="flex items-center gap-2"><Sparkles size={14} className="text-accent" /><span className="text-[13px] font-semibold text-ink">{t("nav.assistant")}</span>{context?.label && <span className="text-[11px] text-faint">· {context.label}</span>}</div>
          <div className="flex items-center gap-1">
            {cid && <button onClick={() => { onClose(); navigate(`/assistant/${cid}`); }} className="rounded-sm px-2 py-1 text-[11px] text-muted hover:bg-surface hover:text-ink" title={t("assistant.openFull")}><Maximize2 size={13} /></button>}
            <button onClick={() => setCid(null)} className="rounded-sm px-2 py-1 text-[11px] text-muted hover:bg-surface hover:text-ink" title={t("assistant.newChat")}><Plus size={13} /></button>
            <button onClick={onClose} className="rounded-sm px-2 py-1 text-muted hover:bg-surface hover:text-ink"><X size={14} /></button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1 flex-col">
          <ChatErrorBoundary>
            <Chat conversationId={cid} onConversationCreated={setCid} context={context} compact />
          </ChatErrorBoundary>
        </div>
      </aside>
    </>
  );
}
