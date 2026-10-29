import { FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { Button, Field, Input } from "../components";
import { TaciteMark } from "../components/TaciteMark";
import { useI18n } from "../i18n/I18nProvider";
import { getToken, login, register, setToken } from "../api";
import { isDesktop, MAC_APP_URL } from "../desktop";

function detailOf(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err);
  const i = raw.indexOf("{");
  if (i >= 0) {
    try {
      const body = JSON.parse(raw.slice(i));
      if (typeof body.detail === "string") return body.detail;
    } catch { /* le corps n'est pas du JSON */ }
  }
  return raw;
}

export default function LoginPage() {
  const { t } = useI18n();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  if (done || getToken()) return <Navigate to="/" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const fn = mode === "login" ? login : register;
      const res = await fn(username, password);
      setToken(res.token);
      setDone(true);
    } catch (err) {
      setError(detailOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-6">
      <form onSubmit={onSubmit} className="w-full max-w-[380px]">
        <div className="h-[2px] w-[52px] bg-accent" />
        <div className="mt-4 flex items-center gap-3">
          <TaciteMark framed size={36} className="overflow-hidden rounded-[8px] ring-1 ring-hair" />
          <div>
            <div className="text-[12px] font-bold uppercase tracking-[0.18em] text-ink">{t("auth.title")}</div>
            <div className="text-[11px] text-faint">{t("brand.press")}</div>
          </div>
        </div>
        <p className="mt-6 text-[13px] leading-relaxed text-muted">{t("auth.subtitle")}</p>
        <div className="mt-6 space-y-4">
          <Field label={t("auth.username")}>
            <Input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label={t("auth.password")} hint={mode === "register" ? t("auth.passwordHint") : undefined}>
            <Input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
        </div>
        {error && <p className="mt-4 text-[12.5px] text-confidential">{error}</p>}
        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            type="button"
            className="text-[12px] text-muted underline decoration-hair underline-offset-2 hover:text-ink"
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}
          >
            {mode === "login" ? t("auth.switchToCreate") : t("auth.switchToSignIn")}
          </button>
          <Button type="submit" variant="primary" disabled={busy || username.trim().length < 3 || password.length < 5}>
            {busy ? t("auth.working") : mode === "login" ? t("auth.signIn") : t("auth.create")}
          </Button>
        </div>
        {!isDesktop() && (
          <p className="mt-8 text-[12px] leading-relaxed text-faint">
            <a className="text-muted underline decoration-hair underline-offset-2 hover:text-ink" href={MAC_APP_URL}>{t("auth.downloadMac")}</a>
            <span className="mt-1 block">{t("auth.downloadMacHint")}</span>
          </p>
        )}
      </form>
    </div>
  );
}
