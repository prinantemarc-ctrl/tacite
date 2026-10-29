import { useState } from "react";
import * as d3 from "d3";
import { T, CHART_FONT } from "../../theme";
import { usePalette } from "../../ThemeProvider";
import { Tip, Tooltip, useWidth } from "./shared";
import { useI18n } from "../../i18n/I18nProvider";

type Props = { data: any; mode: "topic_similarity" | "framing_similarity" };

export default function ProximityMatrix({ data, mode }: Props) {
  const { t, intl, locale } = useI18n();
  const [wrapRef, width] = useWidth<HTMLDivElement>(900);
  const [tip, setTip] = useState<Tip>(null);
  const palette = usePalette();
  const outlets: any[] = data?.outlets || [];
  const order: number[] = data?.order || outlets.map((_: any, i: number) => i);
  const m: number[][] = data?.[mode] || [];

  if (!outlets.length) return <div ref={wrapRef} className="py-8 text-center text-[12.5px] italic text-faint">{t("map.notEnough")}</div>;

  const labelW = 130;
  const cell = Math.max(10, Math.min(26, Math.floor((width - labelW - 8) / outlets.length)));
  const size = cell * outlets.length;
  const height = size + labelW;
  const lo = mode === "framing_similarity" ? -1 : 0;
  const shade = d3.scaleLinear<string>().domain([lo, 1]).range([palette.paper, palette.accentStrong]);

  return (
    <div ref={wrapRef} className="relative select-none overflow-x-auto">
      <svg width={labelW + size + 8} height={height} className="block" style={{ fontFamily: CHART_FONT }} onMouseLeave={() => setTip(null)}>
        <g transform={`translate(${labelW},${labelW})`}>
          {order.map((ri, r) => order.map((ci, c) => {
            const v = m[ri]?.[ci] ?? 0;
            return (
              <rect key={`${r}-${c}`} x={c * cell} y={r * cell} width={cell - 1} height={cell - 1}
                fill={r === c ? T.surface : shade(v)}
                onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                  <><b>{outlets[ri].name}</b> × <b>{outlets[ci].name}</b>
                    <div className="text-muted">{t("map.themesFraming", { t: (data.topic_similarity[ri][ci] * 100).toFixed(0), f: (data.framing_similarity[ri][ci] * 100).toFixed(0) })}</div></>
                ) })} />
            );
          }))}
          {order.map((ri, r) => (
            <text key={`r${r}`} x={-6} y={r * cell + cell / 2} dy="0.35em" textAnchor="end" fontSize={Math.min(10.5, cell - 2)} fill={T.ink}>{outlets[ri].name}</text>
          ))}
          {order.map((ci, c) => (
            <text key={`c${c}`} transform={`translate(${c * cell + cell / 2},-6) rotate(-90)`} fontSize={Math.min(10.5, cell - 2)} fill={T.ink}>{outlets[ci].name}</text>
          ))}
        </g>
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
