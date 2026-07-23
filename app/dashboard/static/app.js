const $ = (s, el = document) => el.querySelector(s);
const api = (p, opts) => fetch("/api" + p, opts).then(r => r.json());

let currentTab = "priority";

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 1600);
}

function badge(el, cls, text) { const b = $("." + cls, el); if (b) b.textContent = text; }

function renderItems(items) {
  const main = $("#content");
  main.innerHTML = "";
  if (!items.length) { main.innerHTML = '<div class="loading">Nothing here right now.</div>'; return; }
  const tpl = $("#item-card");
  for (const it of items) {
    const node = tpl.content.cloneNode(true);
    badge(node, "source", it.source);
    badge(node, "priority", it.priority || "");
    $(".person", node).textContent = it.author || "";
    $(".title", node).textContent = it.title || "(no title)";
    $(".summary", node).textContent = it.summary || "";
    const open = $(".open", node);
    if (it.url) { open.href = it.url; } else { open.classList.add("hidden"); }
    if (it.injection_flag) $(".injection", node).classList.remove("hidden");

    if (it.draft) {
      $(".draft-wrap", node).classList.remove("hidden");
      $(".draft", node).value = it.draft;
      $(".draft-meta", node).textContent =
        `confidence: ${it.confidence || "?"} · review: ${it.review_reason || "—"}`;
      $(".copy", node).onclick = () => {
        navigator.clipboard.writeText($(".draft", node.parentNode.parentNode)?.value || it.draft);
        toast("Copied — paste into the source");
      };
      wireActions(node, it, true);
    } else {
      $(".no-draft", node).classList.remove("hidden");
      wireActions(node, it, false);
    }
    main.appendChild(node);
  }
  // fix copy handler (grab textarea within same card)
  main.querySelectorAll(".card").forEach(card => {
    const ta = $(".draft", card); const copy = $(".copy", card);
    if (copy && ta) copy.onclick = () => { navigator.clipboard.writeText(ta.value); toast("Copied"); };
  });
}

function wireActions(node, it, hasDraft) {
  node.querySelectorAll(".handled").forEach(b => b.onclick = async () => {
    await api(`/items/${it.id}/handled`, { method: "POST" }); load(); });
  node.querySelectorAll(".snooze").forEach(b => b.onclick = async () => {
    await api(`/items/${it.id}/snooze`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hours: 24 }) });
    load(); });
  if (hasDraft) {
    const saveReview = (rejected) => async (e) => {
      const card = e.target.closest(".card");
      const final_text = $(".draft", card).value;
      await api(`/items/${it.id}/review`, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ final_text, rejected }) });
      toast(rejected ? "Marked rejected — it'll learn" : "Saved — it'll learn your voice");
    };
    node.querySelectorAll(".save-review").forEach(b => b.onclick = saveReview(false));
    node.querySelectorAll(".reject").forEach(b => b.onclick = saveReview(true));
  }
}

async function renderSales() {
  const { sales } = await api("/sales");
  const main = $("#content");
  if (!sales.length) { main.innerHTML = '<div class="loading">No promos captured yet.</div>'; return; }
  const rows = sales.map(s => `
    <tr class="${s.contradicts_sale_id ? "contradiction" : ""}">
      <td>${s.vendor || "—"}</td><td>${s.promo_name || "—"}</td>
      <td>${s.discount || "—"}</td><td>${s.coupon_code || "—"}</td>
      <td>${s.start_date || "—"}</td><td>${(s.end_date || "—")} ${s.end_tz || ""}</td>
      <td>${s.free_shipping_threshold || "—"}</td><td>${s.confidence}</td>
      <td>${s.contradicts_sale_id ? "⚠ conflicts w/ #" + s.contradicts_sale_id : ""}</td>
    </tr>`).join("");
  main.innerHTML = `<table class="sales"><thead><tr>
    <th>Vendor</th><th>Promo</th><th>Discount</th><th>Code</th><th>Start</th>
    <th>End</th><th>Free ship</th><th>Conf.</th><th>Flags</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

async function load() {
  const main = $("#content");
  main.innerHTML = '<div class="loading">Loading…</div>';
  if (currentTab === "sales") return renderSales();
  const tabMap = { priority: "priority", community: "community",
    personal: "personal", content: "content", review: "review" };
  const { items } = await api("/items?tab=" + tabMap[currentTab]);
  renderItems(items || []);
}

async function refreshStatus() {
  const st = await api("/status");
  const banner = $("#banner");
  if (st.emergency_stopped) {
    banner.textContent = "⛔ EMERGENCY STOP is active — collection is disabled.";
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
  $("#connector-health").innerHTML = (st.connectors || []).map(c =>
    `<span><span class="dot ${c.status}"></span>${c.name}: ${c.status}` +
    `${c.last_error ? " (" + c.last_error.slice(0, 40) + ")" : ""}</span>`).join("");
}

document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll("#tabs button").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); currentTab = b.dataset.tab; load();
});
$("#run-btn").onclick = async () => { toast("Running…"); await api("/run", { method: "POST" }); load(); refreshStatus(); };
$("#stop-btn").onclick = async () => {
  const st = await api("/status");
  await api("/emergency-stop", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ on: !st.emergency_stopped }) });
  refreshStatus();
};

load(); refreshStatus();
setInterval(refreshStatus, 30000);
