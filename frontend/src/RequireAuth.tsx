import { useEffect, useState } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { getToken, me, setToken } from "./api";

export default function RequireAuth() {
  const [state, setState] = useState<"loading" | "in" | "out">(getToken() ? "loading" : "out");

  useEffect(() => {
    if (!getToken()) {
      setState("out");
      return;
    }
    let live = true;
    me().then(() => { if (live) setState("in"); }).catch(() => {
      setToken("");
      if (live) setState("out");
    });
    return () => { live = false; };
  }, []);

  if (state === "loading") {
    return <div className="flex min-h-screen items-center justify-center bg-paper text-[12px] text-faint">Tacite</div>;
  }
  if (state === "out") return <Navigate to="/login" replace />;
  return <Outlet />;
}
