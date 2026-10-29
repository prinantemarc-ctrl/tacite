const statusEl = document.getElementById("status");
const bar = document.getElementById("bar");
const actions = document.getElementById("actions");

window.tacite.onStatus((s) => {
  statusEl.textContent = s.message || "";
  statusEl.classList.toggle("error", !!s.error);
  bar.classList.toggle("idle", !!s.idle);
  bar.classList.toggle("fail", !!s.error);
  actions.classList.toggle("show", !!s.error);
});

document.getElementById("retry").onclick = () => window.tacite.retry();
