import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileText, Trash2, ExternalLink } from "lucide-react";
import { listArtifacts, deleteArtifact, createReport, listReports, listOutlets, listJournalists, listClients, deleteReport } from "../api";
import { Card, PageHeader, Button, Field, Select, Input, Textarea, Table, Badge, Empty, Loading, Callout } from "../components";
import { flag, countryName, loadIsoCountries } from "../geo";
import { useI18n } from "../i18n/I18nProvider";

const KIND_VALUES = ["outlet", "journalist", "client", "landscape", "country", "topic", "theme"] as const;

export default function ReportsPage() {
  const { t, intl, locale } = useI18n();
  const navigate = useNavigate();
  const [arts, setArts] = useState<any[] | null>(null);
  const [drafts, setDrafts] = useState<any[] | null>(null);
  const [kind, setKind] = useState("outlet");
  const [target, setTarget] = useState("");
  const [country, setCountry] = useState("");
  const [notes, setNotes] = useState("");
  const [weeks, setWeeks] = useState(8);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [outlets, setOutlets] = useState<any[]>([]);
  const [journalists, setJournalists] = useState<any[]>([]);
  const [clients, setClients] = useState<any[]>([]);
  const [iso, setIso] = useState<{ code: string; name: string }[]>([]);

  const kinds = useMemo(() => KIND_VALUES.map((value) => ({
    value,
    label: t(`reports.kind${value[0].toUpperCase()}${value.slice(1)}`),
    help: t(`reports.help${value[0].toUpperCase()}${value.slice(1)}`),
  })), [t]);

  const refresh = () => { listArtifacts().then(setArts); listReports().then(setDrafts); };
  useEffect(() => { refresh(); listOutlets("brief").then(setOutlets); listJournalists().then(setJournalists); listClients().then(setClients); loadIsoCountries().then(setIso); }, []);
  useEffect(() => { setTarget(""); setCountry(""); }, [kind]);

  const followed = useMemo(() => {
    const codes = [...new Set(outlets.map((o) => String(o.country || "").toUpperCase()).filter((c) => c.length === 2))];
    return codes.sort((a, b) => countryName(a).localeCompare(countryName(b), locale));
  }, [outlets, locale]);

  const generate = async () => {
    setBusy(true); setMsg(t("reports.busy"));
    try {
      const r = await createReport({
        kind,
        target: kind === "country" ? country : (target || undefined),
        country: kind === "landscape" || kind === "topic" || kind === "theme" ? (country || undefined) : undefined,
        notes: notes || undefined,
        weeks,
      });
      setMsg(t("reports.ready", { title: r.title }));
      navigate(`/reports/${r.id}`);
    } catch (e: any) { setMsg(t("reports.err", { msg: e.message })); }
    finally { setBusy(false); }
  };
  const remove = async (a: any) => {
    if (!confirm(t("common.confirmDelete", { title: a.title }))) return;
    await deleteArtifact(a.id);
    refresh();
  };
  const removeDraft = async (r: any) => {
    if (!confirm(t("common.confirmDelete", { title: r.title }))) return;
    await deleteReport(r.id);
    refresh();
  };

  const k = kinds.find((x) => x.value === kind)!;
  const needsTarget = kind === "outlet" || kind === "journalist" || kind === "client" || kind === "topic" || kind === "theme";
  const needsCountry = kind === "country";
  const showCountry = kind === "country" || kind === "landscape" || kind === "topic" || kind === "theme";
  const showWeeks = kind === "landscape" || kind === "country" || kind === "theme";
  const canGenerate = !busy && (!needsTarget || !!target) && (!needsCountry || !!country);
  const targetLabel = kind === "topic" || kind === "theme" ? t("reports.subject") : kind === "outlet" ? t("reports.outlet") : kind === "journalist" ? t("reports.journalist") : t("reports.client");

  return (
    <div>
      <PageHeader kicker={t("nav.kReports")} title={t("pages.reports")} subtitle={t("reports.subtitle")} />

      <div className="grid gap-5 lg:grid-cols-[380px_1fr]">
        <Card title={t("reports.generateTitle")} help={["declared", "measured", "gap", "influence"]}>
          <div className="space-y-3">
            <Field label={t("reports.type")}>
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>{kinds.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}</Select>
              <p className="mt-1 text-[11px] text-faint">{k.help}</p>
            </Field>
            {needsTarget && (
              <Field label={targetLabel}>
                {kind === "topic" || kind === "theme" ? <Input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={t("reports.topicPh")} /> : (
                  <Select value={target} onChange={(e) => setTarget(e.target.value)}>
                    <option value="">{t("common.choose")}</option>
                    {(kind === "outlet" ? outlets : kind === "journalist" ? journalists : clients).map((x: any) => <option key={x.id} value={String(x.id)}>{x.name}{kind === "journalist" && x.outlet_name ? ` · ${x.outlet_name}` : ""}</option>)}
                  </Select>
                )}
              </Field>
            )}
            {showCountry && (
              <Field label={t("reports.country")} hint={needsCountry ? undefined : t("reports.optional")}>
                <Select value={country} onChange={(e) => setCountry(e.target.value)}>
                  <option value="">{needsCountry ? t("reports.chooseCountry") : t("common.allCountries")}</option>
                  {followed.length > 0 && (
                    <optgroup label={t("map.followed")}>
                      {followed.map((c) => <option key={`f-${c}`} value={c}>{flag(c)} {countryName(c)}</option>)}
                    </optgroup>
                  )}
                  {iso.length > 0 && (
                    <optgroup label={t("common.allCountries")}>
                      {iso.filter((c) => !followed.includes(c.code)).map((c) => <option key={c.code} value={c.code}>{flag(c.code)} {c.name}</option>)}
                    </optgroup>
                  )}
                </Select>
              </Field>
            )}
            {showWeeks && <Field label={t("reports.period")} hint={t("reports.weeks")}><Input type="number" value={weeks} onChange={(e) => setWeeks(+e.target.value)} /></Field>}
            <Field label={t("reports.notes")} hint={t("reports.optional")}><Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t("reports.notesPh")} /></Field>
            <Button variant="primary" disabled={!canGenerate} onClick={generate}>{busy ? t("reports.generating") : t("reports.generate")}</Button>
            {msg && <Callout>{msg}</Callout>}
          </div>
        </Card>

        <div className="space-y-5">
        <Card title={t("reports.drafts")} aside={drafts ? t("reports.nDrafts", { n: drafts.length, s: drafts.length > 1 ? "s" : "" }) : undefined}>
          {drafts === null ? <Loading /> : drafts.length === 0 ? <Empty>{t("reports.emptyDrafts")}</Empty> : (
            <Table headers={[t("reports.colFile"), t("reports.colStatus"), t("reports.colDate"), ""]} dense>
              {drafts.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/reports/${r.id}`} className="font-medium text-ink hover:text-accent-strong">{r.title || t("common.untitled")}</Link>
                    <div className="text-[11px] text-faint">{kinds.find((x) => x.value === r.kind)?.label}{r.target ? ` · ${r.target}` : ""}</div>
                  </td>
                  <td><Badge tone={r.status === "exported" ? "accent" : "default"}>{r.status === "exported" ? t("reports.statusExported") : t("reports.statusDraft")}</Badge></td>
                  <td className="num text-faint">{r.updated_at ? new Date(r.updated_at).toLocaleString(intl, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : ""}</td>
                  <td className="whitespace-nowrap text-right">
                    <Link to={`/reports/${r.id}`} className="mr-2 inline-block text-faint hover:text-ink" title={t("reports.openEditor")}><ExternalLink size={13} /></Link>
                    <button onClick={() => removeDraft(r)} className="text-faint hover:text-confidential" title={t("common.delete")}><Trash2 size={13} /></button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        <Card title={t("reports.files")} aside={arts ? t("reports.nFiles", { n: arts.length, s: arts.length > 1 ? "s" : "" }) : undefined}>
          {arts === null ? <Loading /> : arts.length === 0 ? <Empty>{t("reports.empty")}</Empty> : (
            <Table headers={[t("reports.colFile"), t("reports.colType"), t("reports.colSize"), t("reports.colDate"), ""]} dense>
              {arts.map((a) => (
                <tr key={a.id}>
                  <td><div className="flex items-center gap-2"><FileText size={13} className="shrink-0 text-accent" /><a href={`${a.url}${a.kind === "pdf" || a.kind === "html" ? "?inline=true" : ""}`} target="_blank" rel="noreferrer" className="font-medium text-ink hover:text-accent-strong">{a.title || a.filename}</a></div>
                    {a.meta?.report_kind && <div className="ml-5 text-[11px] text-faint">{kinds.find((x) => x.value === a.meta.report_kind)?.label} · {a.meta.target}</div>}</td>
                  <td><Badge tone={a.meta?.report_kind ? "accent" : "default"}>{a.kind}</Badge></td>
                  <td className="num text-muted">{t("reports.kb", { n: Math.max(1, Math.round((a.size || 0) / 1024)) })}</td>
                  <td className="num text-faint">{new Date(a.created_at).toLocaleString(intl, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td>
                  <td className="whitespace-nowrap text-right">
                    <a href={a.url} className="mr-2 inline-block text-faint hover:text-ink" title={t("common.download")}><ExternalLink size={13} /></a>
                    <button onClick={() => remove(a)} className="text-faint hover:text-confidential" title={t("common.delete")}><Trash2 size={13} /></button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
        </div>
      </div>
    </div>
  );
}
