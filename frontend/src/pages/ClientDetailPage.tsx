import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ChevronRight, RefreshCw } from "lucide-react";
import {
  getClient, getClientRecommendations, getStrategicMap, getClientHistory,
  updateRecommendation, recordOutcome, triggerRecommendations,
} from "../api";
import {
  Card, Badge, Stat, Table, ActionBadge, RiskBadge, StatusBadge, StanceLabel, Button, Select,
  Loading, ErrorState, PageHeader, Empty, Callout, Term, Modal, Field, Textarea, Input,
} from "../components";
import StrategicMap from "../components/StrategicMap";
import { useI18n } from "../i18n/I18nProvider";

const TYPE_KEYS: Record<string, string> = {
  corporate: "typeCorporate",
  government: "typeGovernment",
  ngo: "typeNgo",
  political: "typePolitical",
};
const LEVEL_KEYS: Record<string, string> = { high: "levelHigh", medium: "levelMedium", low: "levelLow" };
const OUTCOME_KEYS: Record<string, string> = { success: "outSuccess", partial: "outPartial", failure: "outFailure" };
const ACTIONS = ["NOURRIR", "AMORCER", "SURVEILLER", "COOPTER", "CONTOURNER", "DILUER", "RETOURNER", "DIVISER", "ISOLER"];

export default function ClientDetailPage() {
  const { t, intl } = useI18n();
  const { id } = useParams<{ id: string }>();
  const [client, setClient] = useState<any>(null);
  const [recs, setRecs] = useState<any[]>([]);
  const [mapData, setMapData] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [outcomeFor, setOutcomeFor] = useState<{ id: number; kind: string } | null>(null);
  const [lesson, setLesson] = useState("");
  const [metric, setMetric] = useState("");

  const typeLabel = (type: string) => {
    const key = TYPE_KEYS[type];
    return key ? t(`clients.${key}`) : type;
  };
  const levelLabel = (level: string) => {
    const key = LEVEL_KEYS[level];
    return key ? t(`clients.${key}`) : level;
  };
  const outcomeWord = (kind: string) => {
    const key = OUTCOME_KEYS[kind];
    return key ? t(`clients.${key}`) : kind;
  };
  const outcomeTitle = (kind: string) => (
    kind === "success" ? t("clients.outcomeSuccess") : kind === "partial" ? t("clients.outcomePartial") : t("clients.outcomeFailure")
  );
  const recStatusLabel = (status: string) => {
    const key = status === "completed" ? "done" : status;
    const label = t(`status.${key}`);
    return label === `status.${key}` ? status : label;
  };

  const load = () => {
    if (!id) return;
    Promise.all([getClient(+id), getClientRecommendations(+id), getStrategicMap(+id), getClientHistory(+id)])
      .then(([c, r, m, h]) => { setClient(c); setRecs(r); setMapData(m); setHistory(h); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, [id]);

  const generate = async () => {
    if (!id) return;
    setGenerating(true);
    try {
      const r = await triggerRecommendations(+id);
      const n = r.generated ?? 0;
      const k = r.kept ?? 0;
      setToast(t("clients.genToast", { n, s: n > 1 ? "s" : "", k, s2: k > 1 ? "s" : "" }));
      setTimeout(() => setToast(null), 8000);
    } catch {}
    load(); setGenerating(false);
  };
  const updateStatus = async (rid: number, status: string) => { await updateRecommendation(rid, { status }); load(); };
  const openOutcome = (rid: number, kind: string) => { setOutcomeFor({ id: rid, kind }); setLesson(""); setMetric(""); };
  const submitOutcome = async () => {
    if (!outcomeFor || lesson.trim().length < 10) return;
    const impact = metric.trim() ? { note: metric.trim() } : {};
    await recordOutcome(outcomeFor.id, { outcome: outcomeFor.kind, lessons_learned: lesson.trim(), impact_metrics: impact });
    setOutcomeFor(null);
    load();
  };
  const copyChannel = async (value: string) => {
    try { await navigator.clipboard.writeText(value); setToast(t("clients.copied")); setTimeout(() => setToast(null), 2500); } catch {}
  };

  if (loading) return <Loading />;
  if (!client) return <ErrorState>{t("clients.notFound")}</ErrorState>;

  const filtered = recs.filter((r) => (!filter || r.action_type === filter) && (!statusFilter || r.status === statusFilter));
  const hostile = mapData.filter((p) => p.stance < -0.2).length;
  const favorable = mapData.filter((p) => p.stance > 0.2).length;

  return (
    <div>
      <PageHeader
        kicker={t("clients.fileKicker", { type: typeLabel(client.type) })}
        title={client.name}
        subtitle={client.sector || undefined}
        actions={<Button variant="primary" onClick={generate} disabled={generating}><RefreshCw size={13} className={generating ? "animate-spin" : ""} /> {generating ? t("clients.generating") : t("clients.generate")}</Button>}
      />

      {toast && <div className="mb-5"><Callout label={t("common.state")}>{toast}</Callout></div>}

      {(client.adaptive || client.last_outcome) && (
        <div className="mb-5">
          <Callout label={t("clients.learningLoop")}>
            {t("clients.adaptiveLine", { p: client.adaptive?.accessibility_pitch_threshold ?? "—", g: client.adaptive?.gap_exploitable_threshold ?? "—" })}
            {client.last_outcome && <> {t("clients.lastOutcome", { outcome: outcomeWord(client.last_outcome.outcome) })}{client.last_outcome.lessons_learned ? t("clients.lastLesson", { lesson: client.last_outcome.lessons_learned }) : ""}.</>}
          </Callout>
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-6 md:grid-cols-6">
        <Stat label={t("clients.exposure")} value={<span className="text-[18px]">{levelLabel(client.exposure)}</span>} help="exposure" />
        <Stat label={t("clients.riskToleranceShort")} value={<span className="text-[18px]">{levelLabel(client.risk_tolerance)}</span>} tone={client.risk_tolerance === "high" ? "alert" : "ink"} help="risk" />
        <Stat label={t("clients.budget")} value={<span className="text-[18px]">{levelLabel(client.budget_level)}</span>} />
        <Stat label={t("clients.hostileOutlets")} value={hostile} tone={hostile ? "alert" : "ink"} sub={t("clients.positionedOf", { n: mapData.length })} help="stance" />
        <Stat label={t("clients.favorableOutlets")} value={favorable} tone="accent" help="stance" />
        <Stat label={t("clients.recommendations")} value={recs.length} sub={t("clients.pendingCount", { n: recs.filter((r) => r.status === "proposed").length })} help="priority" />
      </div>

      {(client.narratives_push?.length || client.narratives_counter?.length) ? (
        <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2">
          <Callout label={t("clients.narrativesPush")}><ul className="list-disc space-y-0.5 pl-4 marker:text-accent">{client.narratives_push?.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul></Callout>
          <Callout label={t("clients.narrativesCounter")} warn><ul className="list-disc space-y-0.5 pl-4 marker:text-confidential">{client.narratives_counter?.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul></Callout>
        </div>
      ) : null}

      <Card title={t("clients.strategicMap")} help={["stance", "influence", "actions"]} aside={<><Term k="stance">{t("clients.mapStance")}</Term> × <Term k="influence">{t("clients.mapInfluence")}</Term> · {t("clients.mapLegend", { nourish: t("action.NOURRIR"), coopt: t("action.COOPTER"), bypass: t("action.CONTOURNER"), flip: t("action.RETOURNER"), isolate: t("action.ISOLER") })}</>}>
        {mapData.length > 0 ? <StrategicMap data={mapData} onSelect={(p) => {
          if (p.recommendation_id) document.getElementById(`rec-${p.recommendation_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }} /> : <Empty>{t("clients.mapEmpty")}</Empty>}
      </Card>

      <Card
        title={t("clients.recsTitle", { n: filtered.length })}
        help={["actions", "risk", "priority", "adaptive"]}
        className="mt-5"
        aside={
          <span className="flex gap-2">
            <Select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">{t("clients.allActions")}</option>
              {ACTIONS.map((a) => <option key={a} value={a}>{t(`action.${a}`)}</option>)}
            </Select>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">{t("clients.allStatuses")}</option>
              <option value="proposed">{recStatusLabel("proposed")}</option>
              <option value="accepted">{recStatusLabel("accepted")}</option>
              <option value="in_progress">{recStatusLabel("in_progress")}</option>
              <option value="completed">{recStatusLabel("completed")}</option>
              <option value="cancelled">{recStatusLabel("cancelled")}</option>
            </Select>
          </span>
        }
      >
        {filtered.length === 0 ? <Empty>{t("clients.noRecs")}</Empty> : (
          <ol className="divide-y divide-hair">
            {filtered.map((r, idx) => (
              <li key={r.id} id={`rec-${r.id}`} className="py-4 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="num text-[10px] font-bold tracking-[0.1em] text-accent">{String(idx + 1).padStart(2, "0")}</span>
                    <ActionBadge type={r.action_type} />
                    <Link to={`/outlets/${r.outlet_id}`} className="text-[13.5px] font-semibold text-ink hover:text-accent-strong">{r.outlet_name || t("clients.outletFallback", { id: r.outlet_id })}</Link>
                    {r.journalist_name && <Link to={`/journalists/${r.journalist_id}`} className="text-[12px] text-muted hover:text-accent-strong">{t("clients.via", { name: r.journalist_name })}</Link>}
                    {r.contact?.best && r.contact.best.confidence !== "guess" && (
                      <span className="inline-flex items-center gap-1 text-[11.5px] text-muted">
                        <span className="font-mono">{r.contact.best.kind} · {r.contact.best.value}</span>
                        <Button size="sm" variant="ghost" onClick={() => copyChannel(r.contact.best.value)}>{t("clients.copy")}</Button>
                        <Link to={`/journalists/${r.journalist_id}`} className="hover:text-accent-strong">{t("clients.profileLink")}</Link>
                      </span>
                    )}
                    <span className="num text-[11px] text-faint">{t("clients.influencePriority", { n: (r.justification?.influence || 0).toFixed(0), p: r.priority?.toFixed(2) })}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <StanceLabel stance={r.justification?.stance || ""} />
                    <RiskBadge level={r.risk_level} />
                    <StatusBadge status={r.status} />
                  </div>
                </div>

                {r.justification?.summary && <p className="mt-2 max-w-3xl text-[12.5px] text-muted">{r.justification.summary}</p>}

                {r.plan?.length > 0 && (
                  <details className="group mt-2">
                    <summary className="inline-flex cursor-pointer items-center gap-1 text-[11.5px] font-semibold uppercase tracking-[0.1em] text-accent-strong">
                      <ChevronRight size={12} className="transition-transform group-open:rotate-90" /> {t("clients.actionPlan", { n: r.plan.length })}
                    </summary>
                    <ol className="mt-2 grid gap-3 md:grid-cols-3">
                      {r.plan.map((phase: any, i: number) => (
                        <li key={i} className="rounded-sm border border-hair bg-surface p-3">
                          <div className="label mb-1">{phase.phase} <span className="normal-case tracking-normal text-faint">· {phase.weeks}</span></div>
                          <ul className="list-disc space-y-0.5 pl-4 text-[12px] text-muted marker:text-accent">
                            {phase.actions?.map((a: string, j: number) => <li key={j}>{a}</li>)}
                          </ul>
                          {phase.tools?.length > 0 && <div className="mt-1.5 text-[10.5px] text-faint">{t("clients.tools", { list: phase.tools.join(", ") })}</div>}
                        </li>
                      ))}
                    </ol>
                  </details>
                )}

                <div className="mt-3 flex gap-1.5">
                  {r.status === "proposed" && <Button size="sm" variant="primary" onClick={() => updateStatus(r.id, "accepted")}>{t("clients.accept")}</Button>}
                  {r.status === "accepted" && <Button size="sm" variant="primary" onClick={() => updateStatus(r.id, "in_progress")}>{t("clients.start")}</Button>}
                  {r.status === "in_progress" && (
                    <>
                      <Button size="sm" variant="primary" onClick={() => openOutcome(r.id, "success")}>{t("clients.success")}</Button>
                      <Button size="sm" onClick={() => openOutcome(r.id, "partial")}>{t("clients.partial")}</Button>
                      <Button size="sm" variant="danger" onClick={() => openOutcome(r.id, "failure")}>{t("clients.failure")}</Button>
                    </>
                  )}
                  {r.status !== "completed" && r.status !== "cancelled" && <Button size="sm" variant="ghost" onClick={() => updateStatus(r.id, "cancelled")}>{t("common.cancel")}</Button>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>

      {history.length > 0 && (
        <Card title={t("clients.history")} aside={<>{t("clients.feeds")} <Term k="adaptive">{t("clients.adaptiveThresholds")}</Term> {t("clients.engineOf")}</>} help="adaptive" className="mt-5">
          <Table headers={[t("clients.colAction"), t("clients.colOutlet"), t("clients.colOutcome"), t("clients.colLesson"), t("clients.colDate")]} dense>
            {history.slice(0, 20).map((h) => (
              <tr key={h.id}>
                <td><ActionBadge type={h.action_type} /></td>
                <td className="text-muted">{h.outlet_name || t("clients.outletFallback", { id: h.outlet_id })}</td>
                <td><Badge tone={h.outcome === "success" ? "accent" : h.outcome === "partial" ? "default" : "alert"}>{h.outcome === "success" ? t("clients.success") : h.outcome === "partial" ? t("clients.partial") : t("clients.failure")}</Badge></td>
                <td className="max-w-[280px] truncate text-[12px] text-muted">{h.lessons_learned || "—"}</td>
                <td className="num text-faint">{h.completed_at ? new Date(h.completed_at).toLocaleDateString(intl) : "—"}</td>
              </tr>
            ))}
          </Table>
        </Card>
      )}

      {outcomeFor && (
        <Modal
          title={outcomeTitle(outcomeFor.kind)}
          onClose={() => setOutcomeFor(null)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setOutcomeFor(null)}>{t("common.cancel")}</Button>
              <Button variant="primary" onClick={submitOutcome} disabled={lesson.trim().length < 10}>{t("common.save")}</Button>
            </>
          }
        >
          <Field label={t("clients.lesson")} hint={t("clients.lessonHint")}>
            <Textarea value={lesson} onChange={(e) => setLesson(e.target.value)} rows={3} />
          </Field>
          <Field label={t("clients.metric")} hint={t("clients.metricHint")}>
            <Input value={metric} onChange={(e) => setMetric(e.target.value)} />
          </Field>
        </Modal>
      )}

      <div className="closing-rule mt-12" />
    </div>
  );
}
