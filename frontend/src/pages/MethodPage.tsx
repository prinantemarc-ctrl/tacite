import { useEffect, useMemo, useState, type ReactNode } from "react";
import { getConstants, getSettings } from "../api";
import { Card, PageHeader, Callout, Table, Input } from "../components";
import { getGlossary, getGroupLabels, type Group } from "../glossary";
import { useI18n } from "../i18n/I18nProvider";

const ORDER: Group[] = ["positions", "axes", "influence", "journalists", "client", "map", "pipeline", "assistant"];

function Emph({ text }: { text: string }) {
  const parts = text.split(/\*([^*]+)\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : p))}</>;
}

export default function MethodPage() {
  const { t, locale } = useI18n();
  const [constants, setConstants] = useState<any>(null);
  const [settings, setSettings] = useState<any>(null);
  const [q, setQ] = useState("");
  useEffect(() => { getSettings().then(setSettings); }, []);
  useEffect(() => { getConstants().then(setConstants); }, [locale]);

  const groupLabels = getGroupLabels();

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const terms = getGlossary();
    return ORDER.map((g) => ({
      group: g,
      items: Object.entries(terms).filter(([, term]) => term.group === g && (!needle || term.label.toLowerCase().includes(needle) || term.short.toLowerCase().includes(needle) || term.long.toLowerCase().includes(needle))),
    })).filter((g) => g.items.length);
  }, [q, locale]);

  const weights: Record<string, number> = settings?.influence_weights || {};
  const needle = q.trim().toLowerCase();
  const showAxes = !needle || t("method.axes").toLowerCase().includes(needle) || "axes".includes(needle);

  return (
    <div>
      <PageHeader
        kicker={t("method.kicker")}
        title={t("method.title")}
        subtitle={t("method.subtitle")}
        actions={<Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("method.search")} className="w-64" />}
      />

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <Callout label={t("method.measures")}>
          <Emph text={t("method.measuresBody")} />
        </Callout>
        <Callout label={t("method.doesNotMeasure")}>
          {t("method.doesNotMeasureBody")}
        </Callout>
        <Callout label={t("method.whereFrom")}>
          {t("method.whereFromBody")}
        </Callout>
      </div>

      {!q && (
        <Card title={t("method.doctrineTitle")} aside={t("method.doctrineAside")} className="mb-5">
          <p className="mb-4 text-[13px] leading-relaxed text-ink">{t("method.doctrineIntro")}</p>
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-sm border border-hair-soft bg-surface p-3.5">
              <div className="text-[13px] font-semibold text-ink">{t("method.pillar1Title")}</div>
              <div className="mt-0.5 text-[11px] font-medium text-accent-strong">{t("method.pillar1Refs")}</div>
              <p className="mt-2 text-[12px] leading-relaxed text-muted"><Emph text={t("method.pillar1Body")} /></p>
            </div>
            <div className="rounded-sm border border-hair-soft bg-surface p-3.5">
              <div className="text-[13px] font-semibold text-ink">{t("method.pillar2Title")}</div>
              <div className="mt-0.5 text-[11px] font-medium text-accent-strong">{t("method.pillar2Refs")}</div>
              <p className="mt-2 text-[12px] leading-relaxed text-muted"><Emph text={t("method.pillar2Body")} /></p>
            </div>
            <div className="rounded-sm border border-hair-soft bg-surface p-3.5">
              <div className="text-[13px] font-semibold text-ink">{t("method.pillar3Title")}</div>
              <div className="mt-0.5 text-[11px] font-medium text-accent-strong">{t("method.pillar3Refs")}</div>
              <p className="mt-2 text-[12px] leading-relaxed text-muted"><Emph text={t("method.pillar3Body")} /></p>
            </div>
          </div>
        </Card>
      )}

      {showAxes && (
        <>
          <Card title={t("method.layerA")} aside={t("method.layerAAside")} className="mb-5" help="axes">
            <Table headers={[t("method.colAxis"), t("method.colPoleNeg"), t("method.colPolePos")]} dense>
              {(constants?.structural_axes || ["loyalty", "pluralism", "openness", "economy", "order"]).map((a: string) => (
                <tr key={a}>
                  <td className="font-medium text-ink">{t(`axis.${a}`)}</td>
                  <td className="text-muted">{t(`pole.${a}_neg`)}</td>
                  <td className="text-muted">{t(`pole.${a}_pos`)}</td>
                </tr>
              ))}
            </Table>
          </Card>
          {(constants?.kits || []).filter((k: any) => k.id && k.id !== "_structural" && (k.axes || []).length).map((kit: any) => (
            <Card key={kit.id} title={kit.label || kit.id} aside={t("method.axesAside")} className="mb-5" help="axes">
              <Table headers={[t("method.colAxis"), t("method.colPoleNeg"), t("method.colPolePos")]} dense>
                {(kit.axes || []).map((a: any) => (
                  <tr key={a.id}>
                    <td className="font-medium text-ink">{a.label || t(`axis.${a.id}`)}</td>
                    <td className="text-muted">{a.neg || t(`pole.${a.id}_neg`)}</td>
                    <td className="text-muted">{a.pos || t(`pole.${a.id}_pos`)}</td>
                  </tr>
                ))}
              </Table>
            </Card>
          ))}
        </>
      )}

      {!q && settings && (
        <Card title={t("method.thresholds")} aside={t("method.editable")} className="mb-5">
          <div className="grid gap-x-8 gap-y-2 text-[12.5px] md:grid-cols-2">
            <Row k={t("method.rowConf")} v={t("method.valConf")} />
            <Row k={t("method.rowGap")} v={t("method.valGap")} />
            <Row k={t("method.rowExploitable")} v={`> ${settings.gap_exploitable_threshold}`} />
            <Row k={t("method.rowDrift")} v={t("method.valDrift", { n: settings.drift_threshold })} />
            <Row k={t("method.rowStance")} v={t("method.valStance", { h: settings.stance_hostile_threshold, f: settings.stance_favorable_threshold })} />
            <Row k={t("method.rowPitch")} v={`≥ ${settings.accessibility_pitch_threshold}`} />
            <Row k={t("method.rowInfl")} v={t("method.valInfl", { h: settings.influence_high_threshold, m: settings.influence_medium_threshold })} />
            <Row k={t("method.rowDissident")} v={t("method.valDissident")} />
            <Row k={t("method.rowBlock")} v={t("method.valBlock")} />
            <Row k={t("method.rowLeadLag")} v={t("method.valLeadLag")} />
            <Row k={t("method.rowCluster")} v={t("method.valCluster")} />
            <Row k={t("method.rowWeights")} v={Object.entries(weights).map(([k, v]) => `${t(`weight.${k}`)} ${Math.round(v * 100)} %`).join(" · ")} />
            <Row k={t("method.rowLlmCap")} v={settings.max_daily_cost_usd ? `${settings.max_daily_cost_usd} $` : t("method.none")} />
          </div>
        </Card>
      )}

      {groups.map(({ group, items }) => (
        <Card key={group} title={groupLabels[group]} aside={t("method.nTerms", { n: items.length, s: items.length > 1 ? "s" : "" })} className="mb-5">
          <dl className="divide-y divide-hair-soft">
            {items.map(([k, term]) => (
              <div key={k} id={`term-${k}`} className="grid gap-x-6 gap-y-1 py-3 first:pt-0 last:pb-0 md:grid-cols-[220px_1fr]">
                <dt>
                  <div className="text-[13.5px] font-semibold text-ink">{term.label}</div>
                  <div className="mt-0.5 text-[11.5px] italic text-faint">{term.short}</div>
                </dt>
                <dd className="text-[12.5px] leading-[1.6] text-muted">{term.long}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}

      {groups.length === 0 && <p className="py-8 text-center text-[12.5px] italic text-faint">{t("method.noMatch", { q })}</p>}

      <div className="closing-rule mt-12" />
    </div>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-hair-soft py-1">
      <span className="text-muted">{k}</span>
      <span className="num text-right font-medium text-ink">{v}</span>
    </div>
  );
}
