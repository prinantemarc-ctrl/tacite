import { useState } from "react";
import { Mail, AtSign, Link2, Globe, Copy, Check, Plus, Search, EyeOff, Eye, Trash2, ExternalLink } from "lucide-react";
import { Card, Badge, Button, Input, Select, Empty, Term } from "../components";
import { addJournalistContact, discoverJournalistContacts, setContactInvalid, deleteContact } from "../api";
import { useI18n } from "../i18n/I18nProvider";

export type Contact = { id: number; kind: string; label: string; value: string; confidence: "verified" | "probable" | "guess"; method?: string; source_url?: string; note?: string; invalid: boolean; url?: string | null; first_seen?: string };

const CONF_TONE: Record<string, { tone: "accent" | "default" | "faint"; help: string }> = {
  verified: { tone: "accent", help: "journalists.contactVerifiedHelp" },
  probable: { tone: "default", help: "journalists.contactProbableHelp" },
  guess: { tone: "faint", help: "journalists.contactGuessHelp" },
};
const METHOD_KEYS: Record<string, string> = {
  jsonld: "journalists.methodJsonld",
  byline_link: "journalists.methodBylineLink",
  author_page: "journalists.methodAuthorPage",
  article_text: "journalists.methodArticleText",
  pattern: "journalists.methodPattern",
  bluesky_search: "journalists.methodBlueskySearch",
  manual: "journalists.methodManual",
  meta: "journalists.methodMeta",
};
const KINDS = ["email", "x", "bluesky", "mastodon", "linkedin", "instagram", "threads", "phone", "signal", "website", "author_page", "other"];
const KIND_KEYS: Record<string, string> = {
  email: "journalists.kindEmail",
  x: "journalists.kindX",
  bluesky: "journalists.kindBluesky",
  mastodon: "journalists.kindMastodon",
  linkedin: "journalists.kindLinkedin",
  instagram: "journalists.kindInstagram",
  threads: "journalists.kindThreads",
  facebook: "journalists.kindFacebook",
  author_page: "journalists.kindAuthorPage",
  website: "journalists.kindWebsite",
  wikipedia: "journalists.kindWikipedia",
  phone: "journalists.kindPhone",
  signal: "journalists.kindSignal",
  other: "journalists.kindOther",
};

export function kindIcon(kind: string, size = 13) {
  if (kind === "email") return <Mail size={size} />;
  if (["x", "bluesky", "mastodon", "instagram", "threads"].includes(kind)) return <AtSign size={size} />;
  if (["linkedin", "facebook", "wikipedia"].includes(kind)) return <Link2 size={size} />;
  return <Globe size={size} />;
}

export default function ContactsCard({ journalistId, initial, scannedAt }: { journalistId: number; initial: Contact[]; scannedAt?: string | null }) {
  const { t, intl, locale } = useI18n();
  const [contacts, setContacts] = useState<Contact[]>(initial || []);
  const [showInvalid, setShowInvalid] = useState(false);
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState("email");
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const [scan, setScan] = useState<string | null | undefined>(scannedAt);

  const visible = contacts.filter((c) => showInvalid || !c.invalid);
  const direct = contacts.filter((c) => !c.invalid && c.confidence !== "guess" && ["email", "x", "bluesky", "mastodon", "linkedin"].includes(c.kind));

  const discover = async () => {
    setBusy(t("journalists.discoverBusy"));
    try {
      const r = await discoverJournalistContacts(journalistId);
      setContacts(r.contacts);
      setScan(new Date().toISOString());
      setBusy(r.found ? (r.found === 1 ? t("journalists.foundOne") : t("journalists.foundMany", { n: r.found })) : t("journalists.foundNone"));
    } catch (e: any) { setBusy(t("settings.err", { msg: e.message })); }
    setTimeout(() => setBusy(null), 5000);
  };
  const add = async () => {
    if (!value.trim()) return;
    const r = await addJournalistContact(journalistId, { kind, value: value.trim(), note: note || undefined });
    setContacts(r); setAdding(false); setValue(""); setNote("");
  };
  const toggle = async (c: Contact) => { await setContactInvalid(c.id, !c.invalid); setContacts((cs) => cs.map((x) => (x.id === c.id ? { ...x, invalid: !c.invalid } : x))); };
  const remove = async (c: Contact) => { if (!confirm(t("journalists.deleteContactConfirm", { label: c.label, value: c.value }))) return; await deleteContact(c.id); setContacts((cs) => cs.filter((x) => x.id !== c.id)); };
  const copy = (c: Contact) => { navigator.clipboard?.writeText(c.value); setCopied(c.id); setTimeout(() => setCopied(null), 1200); };

  return (
    <Card
      title={t("journalists.contact")}
      help={["contact_channels", "contact_confidence"]}
      aside={
        <span className="flex items-center gap-2">
          {direct.length ? <span><span className="num font-medium text-ink">{direct.length}</span> {direct.length > 1 ? t("journalists.directManyLabel") : t("journalists.directOneLabel")}</span> : <span>{t("journalists.directNone")}</span>}
          {scan && <span>· {t("journalists.scannedOn", { date: new Date(scan).toLocaleDateString(intl) })}</span>}
          <button onClick={() => setShowInvalid(!showInvalid)} className="text-faint hover:text-ink" title={showInvalid ? t("journalists.hideInvalid") : t("journalists.showInvalid")} aria-label={showInvalid ? t("journalists.hideInvalid") : t("journalists.showInvalid")}>{showInvalid ? <EyeOff size={12} /> : <Eye size={12} />}</button>
        </span>
      }
    >
      {visible.length ? (
        <ul className="divide-y divide-hair-soft">
          {visible.map((c) => (
            <li key={c.id} className={`flex items-center gap-3 py-2 text-[12.5px] ${c.invalid ? "opacity-50" : ""}`}>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm bg-tint text-accent-strong">{kindIcon(c.kind)}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="label">{c.label}</span>
                  {c.url ? <a href={c.url} target="_blank" rel="noreferrer" className={`truncate font-mono text-[12.5px] text-ink hover:text-accent-strong ${c.invalid ? "line-through" : ""}`}>{c.value}</a> : <span className={`truncate font-mono text-ink ${c.invalid ? "line-through" : ""}`}>{c.value}</span>}
                  <Badge tone={CONF_TONE[c.confidence]?.tone || "default"}><span title={CONF_TONE[c.confidence] ? t(CONF_TONE[c.confidence].help) : undefined}>{t(`confidence.${c.confidence}`) !== `confidence.${c.confidence}` ? t(`confidence.${c.confidence}`) : c.confidence}</span></Badge>
                </div>
                <div className="mt-0.5 truncate text-[11px] text-faint">
                  {(c.method && METHOD_KEYS[c.method] ? t(METHOD_KEYS[c.method]) : c.method)}{c.source_url && <> · <a href={c.source_url} target="_blank" rel="noreferrer" className="hover:text-accent-strong">{t("journalists.source")} <ExternalLink size={9} className="inline" /></a></>}{c.note && <> · {c.note}</>}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1 text-faint">
                <button onClick={() => copy(c)} className="hover:text-ink" title={t("journalists.copy")} aria-label={t("journalists.copy")}>{copied === c.id ? <Check size={12} className="text-accent" /> : <Copy size={12} />}</button>
                <button onClick={() => toggle(c)} className="hover:text-ink" title={c.invalid ? t("journalists.reactivate") : t("journalists.markInvalid")} aria-label={c.invalid ? t("journalists.reactivate") : t("journalists.markInvalid")}>{c.invalid ? <Eye size={12} /> : <EyeOff size={12} />}</button>
                <button onClick={() => remove(c)} className="hover:text-confidential" title={t("common.delete")} aria-label={t("common.delete")}><Trash2 size={12} /></button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>{t("journalists.emptyContacts")}<Term k="contact_confidence">{t("journalists.emptyContactsGuess")}</Term>{t("journalists.emptyContactsEnd")}</Empty>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-hair-soft pt-3">
        <Button size="sm" onClick={discover} disabled={!!busy}><Search size={12} /> {t("journalists.detect")}</Button>
        <Button size="sm" variant="ghost" onClick={() => setAdding(!adding)}><Plus size={12} /> {t("journalists.add")}</Button>
        {busy && <span className="text-[11.5px] text-muted">{busy}</span>}
      </div>
      {adding && (
        <div className="mt-3 grid gap-2 rounded-sm border border-hair bg-surface p-3 md:grid-cols-[130px_1fr_1fr_auto]">
          <Select value={kind} onChange={(e) => setKind(e.target.value)} aria-label={t("journalists.contact")}>{KINDS.map((k) => <option key={k} value={k}>{KIND_KEYS[k] ? t(KIND_KEYS[k]) : k}</option>)}</Select>
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder={kind === "email" ? t("journalists.emailPlaceholder") : kind === "x" || kind === "bluesky" ? t("journalists.handlePlaceholder") : t("journalists.valuePlaceholder")} className="font-mono" />
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("journalists.notePlaceholder")} />
          <Button size="sm" variant="primary" onClick={add} disabled={!value.trim()}>{t("common.save")}</Button>
        </div>
      )}
    </Card>
  );
}
