const $=(s,e=document)=>e.querySelector(s), $$=(s,e=document)=>[...e.querySelectorAll(s)];
const api=(p,o)=>fetch("/api"+p,o).then(r=>r.json());
const toast=m=>{const t=$("#toast");t.textContent=m;t.classList.add("show");clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove("show"),1700);};
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function fmtDate(iso){if(!iso)return"";const d=new Date(iso);if(isNaN(d))return"";
  const days=Math.floor((Date.now()-d.getTime())/864e5);
  const abs=d.toLocaleDateString(undefined,{month:"short",day:"numeric"});
  const rel=days<=0?"today":days===1?"1d ago":days+"d ago";
  return `${abs} · ${rel}`;}
const LABEL={priority:"Feed",community:"Community",sales:"Sales",content:"Content",personal:"Personal",email:"Email"};
let tab="priority", sub="all";

function avatarClass(cat){
  if(cat==="peptideprice_sales")return"sales";
  if(cat&&cat.startsWith("email"))return"email";
  if(cat==="content")return"content";
  if(cat==="financial_legal"||cat==="personal"||cat==="email_personal")return"personal";
  return"";
}
function pill(p){const x=(p||"fyi").toLowerCase();const c=x==="urgent"?"urgent":x==="today"?"today":"fyi";
  return `<span class="pill ${c}">${x==="urgent"?"Review":x}</span>`;}

function itemCard(it){
  const av=avatarClass(it.category);
  const glyph=av==="sales"?"🏷️":av==="email"?"✉️":av==="content"?"📢":av==="personal"?"👤":"🎓";
  const inj=it.injection_flag?`<div class="flag">🛡 <span><b>Prompt-injection flagged.</b> Treated as data, never executed — surfaced so you can act.</span></div>`:"";
  const draft=it.draft?`<div class="draft"><div class="draft-head"><span class="draft-label">Your draft reply</span><span class="conf ${it.confidence||'low'}">${it.confidence||'low'}</span></div><div class="draft-text" contenteditable="true" spellcheck="false">${esc(it.draft)}</div>${it.review_reason?`<div style="padding:0 13px 10px;font-size:11px;color:var(--faint)">${esc(it.review_reason)}</div>`:""}</div>`:"";
  const open=it.url?`<a class="act" href="${esc(it.url)}" target="_blank">↗ Open</a>`:"";
  const copyBtn=it.draft?`<button class="act primary" data-copy>⧉ Copy reply</button>`:"";
  return `<article class="card" data-id="${it.id}">
    <div class="card-top"><div class="avatar ${av}">${glyph}</div>
      <div class="who"><div class="name">${esc(it.author||"Unknown")}</div>
        <div class="sub"><span class="chip">${esc(it.source)}${it.category?" · "+esc(it.category.replace("_"," ")):""}</span>${it.created_at?` · <span>${fmtDate(it.created_at)}</span>`:""}</div></div>
      ${pill(it.priority)}</div>
    ${it.title?`<div class="content" style="font-weight:600">${esc(it.title)}</div>`:""}
    <div class="content" style="color:var(--muted)">${esc(it.summary||"")}</div>
    ${inj}${draft}
    <div class="actions">${copyBtn}${open}<button class="act" data-handle>✓ Handled</button><button class="act ghost" data-snooze>◷ Snooze</button></div>
  </article>`;
}

function salesCard(s){
  const warn=s.contradicts_sale_id?`<div class="flag">⚠ Conflicts with an earlier promo (#${s.contradicts_sale_id}) — verify the end date before posting.</div>`:"";
  return `<article class="card" data-id="${s.item_id||""}">
    <div class="card-top"><div class="avatar sales">🏷️</div>
      <div class="who"><div class="name">${esc(s.vendor||"Vendor")}</div><div class="sub"><span class="chip sales">PeptidePrice · sale</span></div></div>
      <span class="pill today">New</span></div>
    ${s.promo_name?`<div class="content" style="font-weight:600">${esc(s.promo_name)}</div>`:""}
    <div class="promo"><div class="promo-grid">
      <div class="promo-cell"><div class="k">Discount</div><div class="v big">${esc(s.discount||"—")}</div></div>
      <div class="promo-cell"><div class="k">Code</div><div class="v">${s.coupon_code?`<span class="code mono">${esc(s.coupon_code)}</span>`:"none needed"}</div></div>
      <div class="promo-cell"><div class="k">Free shipping</div><div class="v">${esc(s.free_shipping_threshold||"—")}</div></div>
      <div class="promo-cell"><div class="k">Ends</div><div class="v">${esc(s.end_date||"—")} ${esc(s.end_tz||"")}</div></div>
    </div></div>${warn}
    <div class="actions"><button class="act primary" data-copy>⧉ Copy summary</button><button class="act" data-handle>✓ Add to tracker</button></div>
  </article>`;
}

async function render(){
  const feed=$("#feed");feed.innerHTML='<div class="empty">Loading…</div>';
  $("#subfilter").classList.toggle("on",tab==="email");
  if(tab==="sales"){
    const [{items:sitems},{sales}]=await Promise.all([api("/items?tab=sales"),api("/sales")]);
    const byItem={};(sales||[]).forEach(s=>{if(s.item_id)byItem[s.item_id]=s;});
    const list=(sitems||[]);
    feed.innerHTML=list.length
      ? list.map(it=>byItem[it.id]?salesCard(byItem[it.id]):itemCard(it)).join("")
      : '<div class="empty">No new vendor sales yet. Live sales from your 52 price-tool companies will land here — commission notices, cart nudges and non-vendor promos are filtered out.</div>';
    return;
  }
  const {items}=await api("/items?tab="+tab);
  let list=items||[];
  if(tab==="email"&&sub!=="all")list=list.filter(i=>i.category===sub);
  feed.innerHTML=list.length?list.map(itemCard).join(""):`<div class="empty">Nothing in ${LABEL[tab]} right now.</div>`;
}

async function refreshChrome(){
  const s=await api("/summary");
  Object.entries(s.counts||{}).forEach(([k,v])=>$$(`[data-c="${k}"]`).forEach(e=>e.textContent=v));
  $("#status-text").textContent=`${s.scan.scanned} items · ${s.scan.relevant} relevant · ${s.scan.filtered} filtered · runs every 45 min`;
  $("#banner").classList.toggle("on",s.emergency_stopped);
  if(s.emergency_stopped)$("#banner").textContent="⛔ Emergency stop is active — collection paused.";
  $("#stats").innerHTML=`
    <div class="stat"><div class="num grad">${s.counts.sales}</div><div class="lab">new sales</div></div>
    <div class="stat"><div class="num">${s.scan.scanned}</div><div class="lab">scanned</div></div>
    <div class="stat"><div class="num">${s.scan.filtered}</div><div class="lab">filtered</div></div>
    <div class="stat"><div class="num">${s.scan.flagged}</div><div class="lab">flagged 🛡</div></div>`;
  $("#sales-rail").innerHTML=(s.sales_soon||[]).length?s.sales_soon.map(x=>`<div class="mini"><span>${esc(x.vendor||"—")}</span><span class="v">${esc(x.end||"")}</span></div>`).join(""):'<div class="srcstat">No dated sales yet</div>';
  $("#cal-rail").innerHTML='<div class="srcstat"><span class="dot warn"></span> Google Calendar <span class="pend">connect on Mac</span></div>';
  const dotFor=st=>st==="ok"?"ok":st==="error"?"err":"warn";
  $("#conn-rail").innerHTML=(s.connectors||[]).length?s.connectors.map(c=>`<div class="srcstat"><span class="dot ${dotFor(c.status)}"></span> ${esc(c.name)} <span class="pend">${c.status}</span></div>`).join(""):'<div class="srcstat">No runs yet — hit Run now</div>';
  $("#health").innerHTML=(s.connectors||[]).slice(0,4).map(c=>`<div class="row"><span class="dot ${dotFor(c.status)}"></span> ${esc(c.name)} · ${c.status}</div>`).join("")||'<div class="row"><span class="dot warn"></span> No runs yet</div>';
}

function selectTab(t){tab=t;sub="all";
  $$(".nav-item,.bn").forEach(b=>b.setAttribute("aria-selected",b.dataset.tab===t));
  $$(".seg").forEach(b=>b.setAttribute("aria-selected",b.dataset.sub==="all"));
  $("#ftitle").textContent=LABEL[t]||"Feed";
  render();window.scrollTo({top:0,behavior:"smooth"});}

$("#nav").addEventListener("click",e=>{const b=e.target.closest(".nav-item");if(b)selectTab(b.dataset.tab);});
$("#bnav").addEventListener("click",e=>{const b=e.target.closest(".bn");if(b)selectTab(b.dataset.tab);});
$("#subfilter").addEventListener("click",e=>{const b=e.target.closest(".seg");if(!b)return;
  sub=b.dataset.sub;$$(".seg").forEach(x=>x.setAttribute("aria-selected",x===b));render();});

$("#feed").addEventListener("click",async e=>{
  const card=e.target.closest(".card");if(!card)return;const id=card.dataset.id;
  if(e.target.closest("[data-copy]")){const d=$(".draft-text",card)||$(".content",card);
    navigator.clipboard&&navigator.clipboard.writeText(d.textContent.trim());
    if(id&&$(".draft-text",card))api(`/items/${id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({final_text:$(".draft-text",card).textContent})});
    toast("Copied — paste it into the source");return;}
  if(e.target.closest("[data-handle]")){if(id)await api(`/items/${id}/handled`,{method:"POST"});card.classList.add("gone");setTimeout(()=>{card.remove();refreshChrome();},330);toast("Marked handled");return;}
  if(e.target.closest("[data-snooze]")){if(id)await api(`/items/${id}/snooze`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({hours:24})});card.classList.add("gone");setTimeout(()=>{card.remove();refreshChrome();},330);toast("Snoozed 24h");return;}
});

function toggleTheme(){const r=document.documentElement;const cur=r.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");r.setAttribute("data-theme",cur==="dark"?"light":"dark");}
["#theme","#theme-m"].forEach(s=>{const el=$(s);if(el)el.onclick=toggleTheme;});
["#run","#run-m"].forEach(s=>{const el=$(s);if(el)el.onclick=async()=>{toast("Running…");await api("/run",{method:"POST"});render();refreshChrome();};});
$("#stop").onclick=async()=>{const s=await api("/status");await api("/emergency-stop",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:!s.emergency_stopped})});refreshChrome();};

if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
render();refreshChrome();setInterval(refreshChrome,30000);
