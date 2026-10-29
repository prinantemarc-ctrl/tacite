const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("tacite", {
  onStatus: (cb) => {
    ipcRenderer.on("status", (_e, payload) => cb(payload));
  },
  retry: () => ipcRenderer.invoke("retry"),
  connectCursor: (opts) => ipcRenderer.invoke("connect-cursor", opts),
});
