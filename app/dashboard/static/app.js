const $=(s,e=document)=>e.querySelector(s), $$=(s,e=document)=>[...e.querySelectorAll(s)];
const api=(p,o)=>fetch("/api"+p,o).then(r=>r.json());
const toast=m=>{const t=$("#toast");t.textContent=m;t.classList.add("show");clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove("show"),1700);};
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function fmtDate(iso){if(!iso)return"";const d=new Date(iso);if(isNaN(d))return"";
  const days=Math.floor((Date.now()-d.getTime())/864e5);
  const abs=d.toLocaleDateString(undefined,{month:"short",day:"numeric"});
  const rel=days<=0?"today":days===1?"1d ago":days+"d ago";
  return `${abs} · ${rel}`;}
const LABEL={priority:"Feed",community:"Community",sales:"Sales",tiktok:"TikTok",content:"Content",studio:"Studio",personal:"Personal",email:"Email",handled:"Handled"};
let tab="priority", sub="all", sortMode="newest";

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
  const av=it.source==="tiktok"?"tiktok":avatarClass(it.category);
  const glyph=av==="tiktok"?"♪":av==="sales"?"🏷️":av==="email"?"✉️":av==="content"?"📢":av==="personal"?"👤":"🎓";
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
  $("#sortbar").style.display=(tab==="plan"||tab==="studio")?"none":"";
  if(tab==="plan")return renderPlan();
  if(tab==="studio")return renderStudio();
  const q="&sort="+sortMode;
  if(tab==="sales"){
    const [{items:sitems},{sales}]=await Promise.all([api("/items?tab=sales"+q),api("/sales")]);
    const byItem={};(sales||[]).forEach(s=>{if(s.item_id)byItem[s.item_id]=s;});
    const list=(sitems||[]);
    feed.innerHTML=list.length
      ? list.map(it=>byItem[it.id]?salesCard(byItem[it.id]):itemCard(it)).join("")
      : '<div class="empty">No new vendor sales yet. Live sales from your 52 price-tool companies land here — commission notices, cart nudges and non-vendor promos are filtered out.</div>';
    return;
  }
  const {items}=await api("/items?tab="+tab+q);
  let list=items||[];
  if(tab==="email"&&sub!=="all")list=list.filter(i=>i.category===sub);
  let head="";
  if(tab==="content")head='<div class="rec" id="rec"><h4>✨ Recommend a post from my classroom</h4>'
    +'<div style="font-size:13px;color:var(--muted)">Grounded only in your course content, in your voice.</div>'
    +'<div class="actions"><button class="act primary" id="rec-btn">Generate idea</button></div></div>';
  const empty=tab==="handled"?"Nothing handled yet.":`Nothing in ${LABEL[tab]} right now.`;
  feed.innerHTML=head+(list.length?list.map(itemCard).join(""):`<div class="empty">${empty}</div>`);
  const rb=$("#rec-btn");if(rb)rb.onclick=loadRecommendation;
}

async function renderPlan(){
  const feed=$("#feed");
  const p=await api("/plan");
  const check=t=>{
    const c=t.content;
    const ready=c?`<div class="sched" data-piece="${c.id}" style="margin:2px 0 8px 26px;gap:8px">
        <span style="flex:1;font-size:13px">📝 ${esc(c.title||"(queued draft)")}</span>
        <span class="draft-text" style="display:none">${esc(c.body||"")}</span>
        <button class="act primary" data-copy>⧉ Copy</button>
        <button class="act" data-cstatus="posted">✓ Posted</button></div>`:"";
    return `<label class="todo ${t.done?"done":""}"><input type="checkbox" data-task="${t.id}" ${t.done?"checked":""}><span>${esc(t.label)}</span></label>${ready}`;
  };
  let h=`<div class="planhdr"><h2>Today · ${esc(p.day)}</h2><div class="sub" style="color:var(--muted);font-size:13px">Content targets reset daily · calendar events blended in by time</div></div>`;
  if(p.schedule&&p.schedule.length)
    h+=`<div class="planblock"><h3>📅 Schedule</h3>`+p.schedule.map(e=>
      `<div class="sched"><span class="t">${esc(e.time)}</span><span>${esc(e.title)}</span>${e.url?`<a class="act" href="${esc(e.url)}" target="_blank">Open in Calendar</a>`:""}</div>`).join("")+`</div>`;
  if(p.free&&p.free.length)
    h+=`<div class="planblock"><h3>🟢 Free time</h3><div class="freerow">`+p.free.map(f=>`<span class="chip">${esc(f)}</span>`).join("")+`</div></div>`;
  (p.quotas||[]).forEach(qk=>{
    h+=`<div class="planblock"><h3>${esc(qk.label)}<span class="prog">${qk.done}/${qk.total} done</span></h3>`+qk.tasks.map(check).join("")+`</div>`;});
  if(p.todos&&p.todos.length)
    h+=`<div class="planblock"><h3>✓ To-do</h3>`+p.todos.map(check).join("")+`</div>`;
  feed.innerHTML=h;
}

const CHAN={skool:"◎ Skool",tiktok:"♪ TikTok",substack:"✎ Substack",youtube:"▶ YouTube"};
function pieceCard(p,isAnswer){
  const conf=p.confidence||"low";
  const glyph=isAnswer?"💬":"📢";
  const meta=isAnswer?"answer":(CHAN[p.channel]||p.channel);
  const reason=p.review_reason?`<div style="padding:0 13px 10px;font-size:11px;color:var(--faint)">${esc(p.review_reason)}</div>`:"";
  const hook=(!isAnswer&&p.hook&&p.body&&!p.body.startsWith(p.hook))?`<div class="content" style="font-weight:600">${esc(p.hook)}</div>`:"";
  const cta=(!isAnswer&&p.cta)?`<div style="padding:2px 13px 10px;font-size:12px;color:var(--muted)">↳ ${esc(p.cta)}</div>`:"";
  return `<article class="card" data-piece="${p.id}">
    <div class="card-top"><div class="avatar content">${glyph}</div>
      <div class="who"><div class="name">${esc(p.title||"(untitled)")}</div>
        <div class="sub"><span class="chip content">${esc(meta)}</span> · <span class="conf ${conf}">${conf}</span></div></div>
      <span class="pill today">${esc(p.status||"queued")}</span></div>
    ${hook}
    <div class="draft"><div class="draft-head"><span class="draft-label">${isAnswer?"Canonical answer — edit before posting":"Copy-ready post — edit before posting"}</span></div>
      <div class="draft-text" contenteditable="true" spellcheck="false">${esc(p.body||"")}</div>${reason}</div>
    ${cta}
    <div class="actions">
      <button class="act primary" data-copy>⧉ Copy</button>
      <button class="act" data-cstatus="posted">✓ Posted</button>
      <button class="act ghost" data-cstatus="discarded">✕ Discard</button></div>
  </article>`;
}
function oppCard(o){
  return `<article class="card" data-opp="${o.id}">
    <div class="card-top"><div class="avatar">❓</div>
      <div class="who"><div class="name">${esc(o.question)}</div>
        <div class="sub"><span class="chip">asked ${o.occurrences}×</span></div></div></div>
    <div class="actions"><button class="act primary" data-answer="${o.id}">✨ Draft answer</button>
      <button class="act ghost" data-dismiss="${o.id}">✕ Dismiss</button></div>
  </article>`;
}

async function renderStudio(){
  const feed=$("#feed");feed.innerHTML='<div class="empty">Loading the shelf…</div>';
  const d=await api("/content/studio");
  const st=d.stats||{open_by_channel:{},open_total:0,posted_total:0};
  const chips=Object.keys(CHAN).map(c=>`<span class="chip">${esc(CHAN[c])}: ${st.open_by_channel[c]||0}</span>`).join(" ");
  let h=`<div class="rec" id="studio-head"><h4>✎ Content Studio — your stocked shelf</h4>
    <div style="font-size:13px;color:var(--muted)">${st.open_total} ready to post · ${st.posted_total} posted. Generated in your voice, grounded only in your own content. Nothing posts automatically — you copy and post.</div>
    <div class="freerow" style="margin-top:8px">${chips}</div>
    <div class="actions" style="margin-top:8px;flex-wrap:wrap;gap:6px">
      <input id="seed-input" placeholder="optional topic seed…" style="flex:1;min-width:160px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg)"/>
      <button class="act primary" data-gen="skool">Generate Skool</button>
      <button class="act" data-gen="tiktok">TikTok</button>
      <button class="act" data-gen="substack">Substack</button>
      <button class="act" data-gen="__all">↻ Top up all</button></div></div>`;

  const posts=d.posts||{};
  const anyPosts=Object.values(posts).some(a=>a&&a.length);
  h+=`<div class="planblock"><h3>📢 Post queue</h3>`;
  if(anyPosts){
    Object.keys(CHAN).forEach(c=>{const list=posts[c]||[];if(!list.length)return;
      h+=`<div style="margin:6px 0 2px;font-size:12px;color:var(--muted)">${esc(CHAN[c])} · ${list.length}</div>`+list.map(p=>pieceCard(p,false)).join("");});
  }else h+=`<div class="empty">Queue is empty. Hit “Top up all” (needs your API key + imported content), or the 45-min cycle fills it automatically.</div>`;
  h+=`</div>`;

  const answers=d.answers||[];
  h+=`<div class="planblock"><h3>💬 Answer bank</h3>`;
  h+=answers.length?answers.map(p=>pieceCard(p,true)).join(""):`<div class="empty">No canonical answers yet — draft one from a recurring question below.</div>`;
  h+=`</div>`;

  const opps=(d.opportunities||[]).filter(o=>o.status==="open"&&!o.answer_piece_id);
  if(opps.length){h+=`<div class="planblock"><h3>❓ Recurring questions (no answer yet)</h3>`+opps.map(oppCard).join("")+`</div>`;}
  feed.innerHTML=h;
}

async function loadRecommendation(){
  const rec=$("#rec");if(!rec)return;rec.innerHTML='<h4>✨ Thinking…</h4>';
  const {recommendation:r}=await api("/content/recommendation");
  if(!r){rec.innerHTML='<h4>✨ Recommend a post</h4><div style="font-size:13px;color:var(--muted)">Import your classroom (skool_pull.py --classroom) and set your API key first.</div>';return;}
  rec.innerHTML=`<h4>${esc(r.title||"Post idea")}</h4><div style="font-size:13px;color:var(--muted)">${esc(r.angle||"")}</div>`
    +`<ul>${(r.outline||[]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`
    +`<div class="actions"><button class="act primary" data-copy>⧉ Copy</button><button class="act" id="rec-btn">↻ Another</button></div>`;
  const rb=$("#rec-btn");if(rb)rb.onclick=loadRecommendation;
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
  sub=b.dataset.sub;$$("#subfilter .seg").forEach(x=>x.setAttribute("aria-selected",x===b));render();});
$("#sortbar").addEventListener("click",e=>{const b=e.target.closest(".seg");if(!b)return;
  sortMode=b.dataset.sort;$$("#sortbar .seg").forEach(x=>x.setAttribute("aria-selected",x===b));render();});

async function studioGenerate(channel){
  const seed=($("#seed-input")&&$("#seed-input").value.trim())||"";
  toast("Generating…");
  const body=channel==="__all"?{}:{channel,seed};
  const r=await api("/content/generate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const n=r.created!=null?r.created:(r.answers_created||0)+Object.values(r.posts_created||{}).reduce((a,b)=>a+b,0);
  toast(n?`Added ${n} to the shelf`:(r.reason||"Nothing generated — check API key / imported content"));
  renderStudio();refreshChrome();
}

$("#feed").addEventListener("click",async e=>{
  // Studio: generate buttons (live in the header, not a card)
  const gen=e.target.closest("[data-gen]");
  if(gen){return studioGenerate(gen.dataset.gen);}
  // Studio: a recurring-question card → draft/dismiss
  const oppCardEl=e.target.closest("[data-opp]");
  if(oppCardEl){
    const ans=e.target.closest("[data-answer]"),dis=e.target.closest("[data-dismiss]");
    if(ans){toast("Drafting answer…");await api("/content/generate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({opportunity_id:+ans.dataset.answer})});renderStudio();refreshChrome();return;}
    if(dis){await api(`/content/opportunity/${dis.dataset.dismiss}/dismiss`,{method:"POST"});oppCardEl.classList.add("gone");setTimeout(()=>oppCardEl.remove(),300);toast("Dismissed");return;}
    return;
  }
  // Studio: a queued post/answer card → copy / posted / discard
  const pcard=e.target.closest("[data-piece]");
  if(pcard){
    const pid=pcard.dataset.piece,dt=$(".draft-text",pcard);
    if(e.target.closest("[data-copy]")){dt&&navigator.clipboard&&navigator.clipboard.writeText(dt.textContent.trim());toast("Copied — paste it into Skool");return;}
    const st=e.target.closest("[data-cstatus]");
    if(st){const status=st.dataset.cstatus;
      await api(`/content/piece/${pid}/status`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,edited_text:dt?dt.textContent.trim():null})});
      pcard.classList.add("gone");setTimeout(()=>{pcard.remove();refreshChrome();},300);
      toast(status==="posted"?"Marked posted ✓ (learned your edits)":"Removed from shelf");return;}
    return;
  }
  const card=e.target.closest(".card");if(!card)return;const id=card.dataset.id;
  if(e.target.closest("[data-copy]")){const d=$(".draft-text",card)||$(".content",card);
    navigator.clipboard&&navigator.clipboard.writeText(d.textContent.trim());
    if(id&&$(".draft-text",card))api(`/items/${id}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({final_text:$(".draft-text",card).textContent})});
    toast("Copied — paste it into the source");return;}
  if(e.target.closest("[data-handle]")){if(id)await api(`/items/${id}/handled`,{method:"POST"});card.classList.add("gone");setTimeout(()=>{card.remove();refreshChrome();},330);toast("Marked handled");return;}
  if(e.target.closest("[data-snooze]")){if(id)await api(`/items/${id}/snooze`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({hours:24})});card.classList.add("gone");setTimeout(()=>{card.remove();refreshChrome();},330);toast("Snoozed 24h");return;}
});

$("#feed").addEventListener("change",async e=>{
  const cb=e.target.closest("input[data-task]");if(!cb)return;
  await api(`/plan/task/${cb.dataset.task}/toggle`,{method:"POST"});
  const lbl=cb.closest(".todo");if(lbl)lbl.classList.toggle("done",cb.checked);
  refreshChrome();
});

function toggleTheme(){const r=document.documentElement;const cur=r.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");r.setAttribute("data-theme",cur==="dark"?"light":"dark");}
["#theme","#theme-m"].forEach(s=>{const el=$(s);if(el)el.onclick=toggleTheme;});
["#run","#run-m"].forEach(s=>{const el=$(s);if(el)el.onclick=async()=>{toast("Running…");await api("/run",{method:"POST"});render();refreshChrome();};});
$("#stop").onclick=async()=>{const s=await api("/status");await api("/emergency-stop",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({on:!s.emergency_stopped})});refreshChrome();};

if("serviceWorker" in navigator)navigator.serviceWorker.register("/sw.js").catch(()=>{});
render();refreshChrome();setInterval(refreshChrome,30000);
