import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import ChartBlock, { type ChartSpec } from "./ChartBlock";

const CHART_TYPES = new Set(["bar", "hbar", "line", "area", "scatter", "radar", "axis_strip", "pie"]);

function tryParseChart(raw: string, lang?: string): ChartSpec | null {
  const s = raw.trim();
  if (!s.startsWith("{") || !s.endsWith("}")) return null;
  try {
    const obj = JSON.parse(s);
    if (obj && typeof obj === "object" && CHART_TYPES.has(obj.type) && Array.isArray(obj.data)) {
      return obj as ChartSpec;
    }
    if (lang === "chart" && obj && typeof obj === "object" && Array.isArray(obj.data)) {
      return { type: "hbar", title: obj.title || "", ...obj } as ChartSpec;
    }
  } catch {
    return null;
  }
  return null;
}

/** Markdown de l'assistant, dans la typographie du kit. Les liens internes (/outlets/3…) passent par le routeur. */
export default function Markdown({ text, compact = false }: { text: string; compact?: boolean }) {
  return (
    <div className={`md ${compact ? "md-compact" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const h = href || "";
            if (h.startsWith("/") && !h.startsWith("/api/")) return <Link to={h} className="text-accent-strong underline decoration-accent/40 underline-offset-2 hover:decoration-accent">{children}</Link>;
            return <a href={h} target="_blank" rel="noreferrer" className="text-accent-strong underline decoration-accent/40 underline-offset-2 hover:decoration-accent">{children}</a>;
          },
          table: ({ children }) => <div className="my-2 overflow-x-auto"><table>{children}</table></div>,
          code: ({ className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || "");
            const lang = match?.[1]?.toLowerCase();
            const raw = String(children ?? "").replace(/\n$/, "");
            if (lang === "chart" || lang === "json" || (!lang && raw.includes('"data"') && raw.startsWith("{"))) {
              const spec = tryParseChart(raw, lang);
              if (spec) return <ChartBlock spec={spec} />;
            }
            return <code className={className} {...props}>{children}</code>;
          },
          pre: ({ children }) => {
            const child: any = Array.isArray(children) ? children[0] : children;
            if (child?.type === ChartBlock || child?.props?.spec) return <>{children}</>;
            const raw = String(child?.props?.children ?? "").replace(/\n$/, "");
            const cls = String(child?.props?.className ?? "");
            const match = /language-(\w+)/.exec(cls);
            const spec = tryParseChart(raw, match?.[1]?.toLowerCase());
            if (spec) return <ChartBlock spec={spec} />;
            return <pre>{children}</pre>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
