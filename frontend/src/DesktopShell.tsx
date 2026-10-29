import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { uploadAttachment } from "./api";
import { bridge, pickNativeFiles, stashAttachments, stashOutletCsv } from "./desktop";

/** Écoute les menus natifs. Rien ne s’affiche ; dans le navigateur le pont est absent. */
export default function DesktopShell() {
  const navigate = useNavigate();

  useEffect(() => {
    const b = bridge();
    if (!b?.onMenu) return;
    return b.onMenu(async ({ action }) => {
      if (action === "settings") {
        navigate("/settings");
        return;
      }
      if (action === "refresh") {
        window.location.reload();
        return;
      }
      if (action === "import-outlets") {
        const files = await pickNativeFiles("outlets");
        if (!files[0]) return;
        stashOutletCsv(files[0]);
        navigate("/outlets");
        window.dispatchEvent(new Event("tacite-import-outlets"));
        return;
      }
      if (action === "import-documents") {
        const files = await pickNativeFiles("documents");
        if (!files.length) return;
        const uploaded: { name: string; text: string; chars: number }[] = [];
        for (const file of files) {
          try {
            uploaded.push(await uploadAttachment(file));
          } catch (err) {
            const message = err instanceof Error ? err.message : String(err);
            await b.showNotification?.("Tacite", message);
          }
        }
        if (!uploaded.length) return;
        stashAttachments(uploaded);
        navigate("/assistant");
        window.dispatchEvent(new Event("tacite-attachments"));
        await b.showNotification?.("Tacite", `${uploaded.length} document${uploaded.length > 1 ? "s" : ""} prêt${uploaded.length > 1 ? "s" : ""} pour l’assistant`);
      }
    });
  }, [navigate]);

  return null;
}
