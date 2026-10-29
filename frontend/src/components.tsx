import { Component, ReactNode, SelectHTMLAttributes, InputHTMLAttributes, TextareaHTMLAttributes, ButtonHTMLAttributes, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, X } from "lucide-react";
import { term } from "./glossary";
import { translate } from "./i18n/I18nProvider";

/* ------------------------------------------------------------ Glossaire */
/** Terme défini : souligné pointillé bronze, définition courte au survol. */
export function Term({ k, children, className = "" }: { k: string; children?: ReactNode; className?: string }) {
  const t = term(k);
  return (
    <span className={`group/term relative inline-block ${className}`}>
      <span className="cursor-help border-b border-dotted border-accent/60">{children ?? t.label}</span>
      <span className="pointer-events-none absolute left-0 top-full z-30 mt-1.5 hidden w-64 rounded-sm border border-hair bg-paper px-3 py-2 text-left text-[11.5px] normal-case leading-snug tracking-normal text-ink shadow-[0_8px_24px_-12px_rgba(0,0,0,.25)] group-hover/term:block">
        <span className="label mb-0.5 block">{t.label}</span>
        <span className="font-normal text-muted">{t.short}</span>
      </span>
    </span>
  );
}

/** Pastille « ? » : définition longue au clic, lien vers la page Méthode. */
export function Help({ k, keys }: { k?: string; keys?: string[] }) {
  const [open, setOpen] = useState(false);
  const list = (keys || (k ? [k] : [])).map(term);
  if (!list.length) return null;
  return (
    <span className="relative inline-block align-middle">
      <button
        type="button" aria-label={translate("common.explain")} onClick={() => setOpen((v) => !v)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={`ml-1.5 inline-flex h-[15px] w-[15px] items-center justify-center rounded-full border text-[9.5px] font-bold leading-none transition-colors ${open ? "border-accent bg-accent text-paper" : "border-faint text-faint hover:border-accent hover:text-accent-strong"}`}
      >?</button>
      {open && (
        <span className="absolute left-0 top-full z-30 mt-2 block w-80 rounded-sm border border-hair bg-paper p-3.5 text-left text-[12px] normal-case leading-snug tracking-normal shadow-[0_12px_32px_-12px_rgba(0,0,0,.3)]">
          {list.map((t) => (
            <span key={t.label} className="mb-3 block last:mb-0">
              <span className="label mb-1 block">{t.label}</span>
              <span className="block font-normal text-muted">{t.long}</span>
            </span>
          ))}
          <Link to="/method" className="mt-2 block text-[11px] font-semibold uppercase tracking-[0.1em] text-accent-strong hover:underline">{translate("common.more")}</Link>
        </span>
      )}
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════
   Composants Tacite — langage visuel du kit rapport Gorgone.
   Palette close : paper / ink / muted / faint / accent (bronze) / hair /
   surface / tint / confidential. Aucun autre ton.
═══════════════════════════════════════════════════════════════════════ */

/* ------------------------------------------------------------- PageHeader */
export function PageHeader({
  kicker, title, subtitle, actions, children,
}: { kicker?: string; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <header className="border-b-[1.5px] border-accent pb-4 mb-6">
      <div className="flex items-end justify-between gap-6">
        <div className="min-w-0">
          {kicker && <div className="kicker mb-1.5">{kicker}</div>}
          <h1 className="text-[26px] font-bold leading-[1.12] tracking-[-0.02em] text-ink">{title}</h1>
          {subtitle && <p className="mt-1.5 text-[13px] text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2 pb-0.5">{actions}</div>}
      </div>
      {children}
    </header>
  );
}

/* --------------------------------------------------------------- Section */
/** Étiquette de rubrique en petites capitales bronze, soulignée d'un filet. */
export function SectionTitle({ children, aside, help }: { children: ReactNode; aside?: ReactNode; help?: string | string[] }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4 border-b border-hair pb-1.5">
      <h3 className="label flex items-center">{children}{help && <Help keys={Array.isArray(help) ? help : [help]} />}</h3>
      {aside && <div className="text-[11px] text-faint">{aside}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ Card */
export function Card({
  children, className = "", title, aside, tone = "paper", help,
}: { children: ReactNode; className?: string; title?: ReactNode; aside?: ReactNode; tone?: "paper" | "surface"; help?: string | string[] }) {
  return (
    <section className={`rounded-kit border border-hair p-4 ${tone === "surface" ? "bg-surface" : "bg-paper"} ${className}`}>
      {title && <SectionTitle aside={aside} help={help}>{title}</SectionTitle>}
      {children}
    </section>
  );
}

/* ------------------------------------------------------------------ Stat */
/** Cartouche de couverture : étiquette bronze, valeur, filet bronze à gauche. */
export function Stat({ label, value, sub, tone = "ink", help }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "ink" | "accent" | "alert"; help?: string;
}) {
  const color = tone === "accent" ? "text-accent-strong" : tone === "alert" ? "text-confidential" : "text-ink";
  return (
    <div className="border-l-[1.5px] border-accent pl-3">
      <div className="label mb-1">{help ? <Term k={help}>{label}</Term> : label}</div>
      <div className={`num text-[24px] font-bold leading-none tracking-[-0.02em] ${color}`}>{value}</div>
      {sub && <div className="mt-1 text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

/* ----------------------------------------------------------------- Badge */
export type Tone = "default" | "accent" | "ink" | "alert" | "faint";
const LEGACY: Record<string, Tone> = {
  gray: "default", blue: "default", indigo: "accent", green: "accent", yellow: "ink", red: "alert",
};
const TONE_CLASS: Record<Tone, string> = {
  default: "border-hair text-muted bg-paper",
  faint: "border-hair-soft text-faint bg-paper",
  accent: "border-transparent text-accent-strong bg-tint",
  ink: "border-transparent text-paper bg-ink",
  alert: "border-confidential/40 text-confidential bg-paper",
};
export function Badge({ children, tone, color, mono = false, className = "" }: {
  children: ReactNode; tone?: Tone; color?: string; mono?: boolean; className?: string;
}) {
  const t: Tone = tone || (color ? LEGACY[color] || "default" : "default");
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-pill border px-2 py-[1px] text-[10px] font-semibold uppercase tracking-[0.08em] leading-[1.6] ${mono ? "font-mono normal-case tracking-normal" : ""} ${TONE_CLASS[t]} ${className}`}>
      {children}
    </span>
  );
}

/* ---------------------------------------------------------- Domain badges */
const ACTION_TONE: Record<string, Tone> = {
  NOURRIR: "accent", AMORCER: "accent", SURVEILLER: "default",
  COOPTER: "ink", CONTOURNER: "ink", DILUER: "ink",
  RETOURNER: "alert", DIVISER: "alert", ISOLER: "alert",
};
export function ActionBadge({ type }: { type: string }) {
  return <Badge tone={ACTION_TONE[type] || "default"}>{translate(`action.${type}`) !== `action.${type}` ? translate(`action.${type}`) : type}</Badge>;
}

export function RiskBadge({ level }: { level: string }) {
  const tone: Record<string, Tone> = { low: "default", medium: "ink", high: "alert" };
  const labels: Record<string, string> = { low: translate("common.riskLow"), medium: translate("common.riskMid"), high: translate("common.riskHigh") };
  return <Badge tone={tone[level] || "default"}>{labels[level] || level}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Record<string, Tone> = {
    proposed: "default", accepted: "accent", in_progress: "ink", completed: "accent", cancelled: "faint",
  };
  const key = status === "completed" ? "done" : status === "cancelled" ? "cancelled" : status;
  const mapped = translate(`status.${key}`);
  return <Badge tone={tone[status] || "default"}>{mapped !== `status.${key}` ? mapped : (status === "cancelled" ? translate("common.cancelled") : status)}</Badge>;
}

export function StanceLabel({ stance }: { stance: string }) {
  const tone: Record<string, Tone> = { hostile: "alert", neutre: "default", favorable: "accent", neutral: "default" };
  const key = stance === "neutre" ? "neutral" : stance;
  const mapped = translate(`stance.${key}`);
  return <Badge tone={tone[stance] || "default"}>{mapped !== `stance.${key}` ? mapped : (stance || "—")}</Badge>;
}

/* ----------------------------------------------------------------- Table */
export function Table({ headers, children, dense = false }: { headers: (string | ReactNode)[]; children: ReactNode; dense?: boolean }) {
  return (
    <div className="overflow-x-auto -mx-4 px-4">
      <table className={`w-full border-collapse text-[12.5px] ${dense ? "[&_td]:py-1.5" : "[&_td]:py-2"} [&_td]:px-2.5 [&_td]:border-b [&_td]:border-hair-soft [&_td]:align-top [&_tbody_tr:last-child_td]:border-0 [&_tbody_tr:nth-child(even)_td]:bg-surface/40 [&_tbody_tr:hover_td]:bg-tint`}>
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="label whitespace-nowrap border-y border-hair bg-tint px-2.5 py-1.5 text-left font-bold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/* ----------------------------------------------------------------- Meter */
/** Barre de mesure 0–100. Le ton alerte n'est utilisé que sur demande. */
export function Meter({ value, max = 100, tone = "accent", width = "w-16", label }: {
  value: number; max?: number; tone?: "accent" | "ink" | "alert" | "muted"; width?: string; label?: ReactNode;
}) {
  const pct = Math.max(0, Math.min((value / max) * 100, 100));
  const fill = { accent: "bg-accent", ink: "bg-ink", alert: "bg-confidential", muted: "bg-faint" }[tone];
  return (
    <div className="flex items-center gap-2">
      <div className={`${width} h-[3px] rounded-pill bg-hair`}>
        <div className={`h-full rounded-pill ${fill}`} style={{ width: `${pct}%` }} />
      </div>
      {label !== undefined && <span className="num text-[11px] text-muted">{label}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------- GapBar */
/** Écart signé, centré sur zéro. Bronze ; rouge sourd au-delà de 0,5. */
export function GapBar({ value, max = 1 }: { value: number; max?: number }) {
  const abs = Math.abs(value);
  const pct = Math.min((abs / max) * 50, 50);
  const fill = abs > 0.5 ? "bg-confidential" : abs > 0.3 ? "bg-accent" : "bg-faint";
  return (
    <div className="flex items-center gap-2">
      <div className="relative h-[3px] flex-1 rounded-pill bg-hair">
        <div className="absolute inset-y-[-2px] left-1/2 w-px bg-faint" />
        <div
          className={`absolute inset-y-0 rounded-pill ${fill}`}
          style={value >= 0 ? { left: "50%", width: `${pct}%` } : { right: "50%", width: `${pct}%` }}
        />
      </div>
      <span className="num w-11 text-right text-[11px] text-muted">{value > 0 ? "+" : ""}{value.toFixed(2)}</span>
    </div>
  );
}

/* ---------------------------------------------------------------- Button */
type Variant = "primary" | "secondary" | "ghost" | "danger";
const BTN: Record<Variant, string> = {
  primary: "bg-accent text-paper hover:bg-accent-strong border-transparent",
  secondary: "bg-paper text-ink border-hair hover:bg-surface hover:border-faint",
  ghost: "bg-transparent text-muted border-transparent hover:text-ink hover:bg-surface",
  danger: "bg-paper text-confidential border-confidential/30 hover:bg-confidential hover:text-paper",
};
export function Button({ variant = "secondary", size = "md", className = "", children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  const sz = size === "sm" ? "px-2.5 py-1 text-[11.5px]" : "px-3.5 py-1.5 text-[12.5px]";
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-sm border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${sz} ${BTN[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Bouton d'icône discret (éditer / supprimer). */
export function IconButton({ className = "", danger = false, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { danger?: boolean }) {
  return (
    <button
      className={`rounded-sm p-1 text-faint transition-colors hover:bg-surface ${danger ? "hover:text-confidential" : "hover:text-accent-strong"} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/* --------------------------------------------------------------- Segmented */
export function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[];
}) {
  return (
    <div className="inline-flex rounded-sm border border-hair bg-paper p-[2px]">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-[2px] px-3 py-1 text-[12px] font-medium transition-colors ${
            value === o.value ? "bg-ink text-paper" : "text-muted hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------- Forms */
export function Field({ label, hint, children, className = "" }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className="label mb-1 block">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </label>
  );
}
export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`field ${className}`} {...rest} />;
}
export function Textarea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`field resize-y ${className}`} {...rest} />;
}
export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={`relative inline-block ${className}`}>
      <select className="field pr-7" {...rest}>{children}</select>
      <ChevronDown size={13} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-faint" />
    </span>
  );
}

/* ----------------------------------------------------------------- Modal */
export function Modal({ title, onClose, children, footer, width = "max-w-lg" }: {
  title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/30 p-6 backdrop-blur-[1px]" onMouseDown={onClose}>
      <div
        className={`my-8 w-full ${width} rounded-kit border border-hair bg-paper shadow-[0_20px_60px_-20px_rgba(0,0,0,0.25)]`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b-[1.5px] border-accent px-5 py-3.5">
          <h3 className="text-[15px] font-bold tracking-[-0.01em]">{title}</h3>
          <IconButton onClick={onClose} aria-label={translate("common.close")}><X size={16} /></IconButton>
        </div>
        <div className="space-y-3.5 px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-hair px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- Callout */
/** Encadré du kit : fond gris, filet bronze à gauche ; variante d'alerte. */
export function Callout({ label, children, warn = false }: { label?: ReactNode; children: ReactNode; warn?: boolean }) {
  return (
    <div className={`rounded-sm border border-hair border-l-[2.5px] bg-surface px-3.5 py-2.5 ${warn ? "border-l-confidential" : "border-l-accent"}`}>
      {label && <div className={`label mb-1 ${warn ? "text-confidential" : ""}`}>{label}</div>}
      <div className="text-[12.5px] text-muted">{children}</div>
    </div>
  );
}

/* ---------------------------------------------------------------- Empty */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-[12.5px] italic text-faint">{children}</p>;
}

export function Loading() {
  return <div className="p-10 text-[12.5px] italic text-faint">{translate("common.loading")}</div>;
}
export function ErrorState({ children }: { children: ReactNode }) {
  return <div className="p-10"><Callout label={translate("common.error")} warn>{children}</Callout></div>;
}

/** Empêche un plantage du chat (graphique, markdown) de vider toute la page. */
export class ChatErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state: { err: Error | null } = { err: null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="flex min-h-0 flex-1 flex-col items-start justify-center gap-3 p-8">
        <ErrorState>{this.state.err.message || translate("common.error")}</ErrorState>
        <button type="button" className="rounded-sm border border-hair px-3 py-1.5 text-[12px] text-muted hover:border-faint hover:text-ink" onClick={() => this.setState({ err: null })}>
          {translate("common.close")}
        </button>
      </div>
    );
  }
}

/* ---------------------------------------------------------------- Score */
/** Grand chiffre de score, à droite d'un en-tête. */
export function Score({ value, label, tone = "accent" }: { value: number; label: string; tone?: "accent" | "ink" | "alert" }) {
  const color = tone === "accent" ? "text-accent-strong" : tone === "alert" ? "text-confidential" : "text-ink";
  return (
    <div className="text-right">
      <div className={`num text-[34px] font-bold leading-none tracking-[-0.03em] ${color}`}>{value.toFixed(0)}</div>
      <div className="label mt-1">{label}</div>
    </div>
  );
}

/** Pastille de note (score d'accessibilité) — bronze ; sourd si faible. */
export function ScorePill({ value }: { value: number }) {
  const v = value || 0;
  const cls = v >= 70 ? "bg-accent text-paper" : v >= 40 ? "bg-tint text-accent-strong" : "bg-surface text-faint";
  return <span className={`num inline-block rounded-[2px] px-1.5 py-[1px] text-[10px] font-bold ${cls}`}>{v.toFixed(0)}</span>;
}
