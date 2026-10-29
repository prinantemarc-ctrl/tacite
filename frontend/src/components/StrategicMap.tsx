import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ZAxis,
  ReferenceLine,
} from "recharts";
import { useNavigate } from "react-router-dom";
import { T, axisTick, tooltipStyle } from "../theme";
import { useI18n } from "../i18n/I18nProvider";

/** Trois familles d'action, trois tons : favorable (bronze), veille (gris), offensif (rouge sourd). */
const ACTION_TONE: Record<string, string> = {
  NOURRIR: T.accent, AMORCER: T.accent,
  SURVEILLER: T.faint,
  COOPTER: T.ink, CONTOURNER: T.ink, DILUER: T.ink,
  RETOURNER: T.confidential, DIVISER: T.confidential, ISOLER: T.confidential,
};

interface Point {
  outlet_id: number;
  outlet_name: string;
  stance: number;
  influence: number;
  action_type: string | null;
  recommendation_id?: number | null;
}

export default function StrategicMap({ data, onSelect }: { data: Point[]; onSelect?: (p: Point) => void }) {
  const { t, intl, locale } = useI18n();
  const navigate = useNavigate();

  const click = (p: any) => {
    if (!p) return;
    if (onSelect) { onSelect(p); return; }
    if (p.recommendation_id) {
      document.getElementById(`rec-${p.recommendation_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (p.outlet_id) navigate(`/outlets/${p.outlet_id}`);
  };

  return (
    <ResponsiveContainer width="100%" height={420}>
      <ScatterChart margin={{ top: 10, right: 20, bottom: 24, left: 8 }}>
        <CartesianGrid stroke={T.hairSoft} />
        <ReferenceLine x={0} stroke={T.hair} />
        <XAxis
          type="number" dataKey="stance" domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]}
          tick={axisTick} axisLine={{ stroke: T.hair }} tickLine={false}
          label={{ value: t("map.hostileFav"), position: "bottom", fill: T.faint, fontSize: 10, offset: 8, letterSpacing: "0.1em" }}
        />
        <YAxis
          type="number" dataKey="influence" domain={[0, 100]}
          tick={axisTick} axisLine={false} tickLine={false}
          label={{ value: t("map.influence"), angle: -90, position: "insideLeft", fill: T.faint, fontSize: 10, letterSpacing: "0.1em" }}
        />
        <ZAxis type="number" dataKey="influence" range={[60, 520]} />
        <Tooltip
          cursor={{ strokeDasharray: "3 3", stroke: T.hair }}
          contentStyle={tooltipStyle}
          formatter={(_: any, __: any, props: any) => [
            `${props.payload.outlet_name} — ${t("carto.strategicTip", { inf: props.payload.influence?.toFixed(0), st: props.payload.stance?.toFixed(2) })}`,
          ]}
        />
        <Scatter data={data} onClick={click} style={{ cursor: "pointer" }}>
          {data.map((entry, i) => {
            const c = ACTION_TONE[entry.action_type || ""] || T.faint;
            return <Cell key={i} fill={c} fillOpacity={0.55} stroke={c} strokeWidth={1} />;
          })}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}
