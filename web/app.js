/* Mandate demo UI — reads a recorded run (data/run.json) or the live agent API. */
const EXPLORER = "https://explorer-test.qday.info";
const REASONS = {
  1: "Mandate paused", 2: "Policy or invoice expired", 3: "Payee not verified",
  4: "Payee disabled", 5: "Payee name not verified", 6: "Payout address does not match the verified wallet",
  7: "Invoice already settled", 8: "Zero amount", 9: "Above the per-payment cap",
  10: "Above today's remaining cap", 11: "Owner approval required", 12: "Owner signature invalid",
  13: "Mandate underfunded", 14: "Not the agent", 15: "Invoice signature invalid",
  16: "Invoice settlement window closed", 17: "Malformed invoice",
};

const S = { data: null, api: false, selected: null, busy: false, timer: null };

const $ = (sel, root = document) => root.querySelector(sel);
const keyOf = (c) => c.caseId || c.id;
const fmt = (atomic) => (Number(atomic) / 1e6).toFixed(2);
const short = (addr) => (addr && addr.length > 12 ? `${addr.slice(0, 6)}…${addr.slice(-4)}` : addr || "—");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const date = (sec) => new Date(sec * 1000).toISOString().slice(0, 10);

const STATUS = {
  settled: { cls: "paid", label: "Paid" },
  refused: { cls: "refused", label: "Refused" },
  needs_approval: { cls: "wait", label: "Awaiting owner" },
  pending: { cls: "pending", label: "New" },
};

async function boot() {
  // Live agent API (local run) first, recorded snapshot for the public demo.
  try {
    const res = await fetch("api/state", { cache: "no-store" });
    if (res.ok) {
      S.data = await res.json();
      S.api = true;
    }
  } catch (_) { /* static hosting */ }
  if (!S.data) {
    S.data = await (await fetch("data/run.json", { cache: "no-store" })).json();
  }
  S.selected = S.data.cases[0] ? keyOf(S.data.cases[0]) : null;
  const wanted = new URLSearchParams(location.search).get("case");
  if (wanted && S.data.cases.some((c) => keyOf(c) === wanted)) S.selected = wanted;
  render();
  if (new URLSearchParams(location.search).get("replay") === "1") renderPanel(true);
  if (!S.api) liveProbe();
}

function render() {
  const d = S.data;
  const m = d.mandate;
  $("#liveBadge").textContent = S.api ? "live · local agent" : "recorded run";
  $("#liveBadge").classList.toggle("live", S.api);
  $("#netDot").classList.toggle("on", true);
  $("#contractLink").href = `${EXPLORER}/address/${m.address}`;
  $("#contractLink").textContent = `Contract ${short(m.address)}`;
  $("#footerContract").textContent = m.address;
  $("#chainMeta").textContent = `${d.network.name} · ${d.events.length} events · generated ${d.generatedAt.replace("T", " ").slice(0, 19)} UTC`;
  renderStats();
  renderCases();
  renderPolicy();
  renderEvents();
  renderPanel();
}

function renderStats() {
  const m = S.data.mandate;
  const p = m.policy;
  const spent = m.spentToday;
  const pct = Math.min(100, (spent / p.dailyCap) * 100);
  $("#stats").innerHTML = `
    <div class="stat ok">
      <div class="label">Mandate balance</div>
      <div class="value" data-live="balance">${fmt(m.balance)}<small>tUSD8</small></div>
      <div class="sub" id="remainingChip">held by the contract, not the agent</div>
    </div>
    <div class="stat">
      <div class="label">Spent today</div>
      <div class="value">${fmt(spent)}<small>/ ${fmt(p.dailyCap)}</small></div>
      <div class="bar"><i style="width:${pct}%"></i></div>
    </div>
    <div class="stat">
      <div class="label">Invoices settled</div>
      <div class="value">${S.data.totals.settled}<small>of ${S.data.cases.length}</small></div>
      <div class="sub">${fmt(S.data.totals.paid)} tUSD8 paid out</div>
    </div>
    <div class="stat">
      <div class="label">Blocked by the mandate</div>
      <div class="value">${S.data.totals.refused}<small>refused</small></div>
      <div class="sub">each one recorded on chain</div>
    </div>`;
}

function renderCases() {
  const wrap = $("#cases");
  $("#inboxCount").textContent = `${S.data.cases.length} invoices · ${S.data.company}`;
  wrap.innerHTML = S.data.cases
    .map((c) => {
      const st = STATUS[c.status] || STATUS.pending;
      const why = caseWhy(c);
      return `
      <button class="case ${keyOf(c) === S.selected ? "active" : ""} ${c.meta?.kind === "spoof" ? "spoof" : ""}" data-case="${esc(keyOf(c))}">
        <div class="case-top">
          <span class="case-subject">${esc(c.meta?.subject || c.id)}</span>
          <span class="chip ${st.cls}">${st.label}</span>
        </div>
        <div class="case-meta">
          <span class="case-amount">${fmt(Number(c.amount) * 1e6)} tUSD8</span>
          <span>·</span>
          <span>${esc(c.meta?.from || c.issuer.name)}</span>
        </div>
        <div class="case-why ${why.bad ? "bad" : why.good ? "good" : ""}">${esc(why.text)}</div>
      </button>`;
    })
    .join("");
  wrap.querySelectorAll("[data-case]").forEach((el) =>
    el.addEventListener("click", () => {
      S.selected = el.dataset.case;
      renderCases();
      renderPanel(true);
    })
  );
}

function caseWhy(c) {
  if (!c.decision) return { text: "Not processed yet" };
  if (c.status === "settled") {
    return { good: true, text: c.decision.outcome === "owner_approved"
      ? "Owner co-signed, then the agent settled it in tUSD8."
      : "Paid automatically inside the mandate." };
  }
  if (c.status === "refused") return { bad: true, text: `Blocked: ${REASONS[c.decision.reason] || c.decision.reasonLabel}.` };
  if (c.status === "needs_approval") return { text: "Above the approval line — waiting for the owner's signature." };
  return { text: "Ready for the agent" };
}

function renderPolicy() {
  const m = S.data.mandate;
  const p = m.policy;
  $("#policy").innerHTML = `
    <h3>The mandate</h3>
    <div class="row"><span>Per payment</span><b>${fmt(p.perPaymentCap)} tUSD8</b></div>
    <div class="row"><span>Per day</span><b>${fmt(p.dailyCap)} tUSD8</b></div>
    <div class="row"><span>Owner approval above</span><b>${fmt(p.approvalThreshold)} tUSD8</b></div>
    <div class="row"><span>Policy expires</span><b>${p.policyExpiry ? date(p.policyExpiry) : "never"}</b></div>
    <div class="row"><span>Agent key</span><b>${short(m.agent)}</b></div>
    <div class="payees">
      <div class="k" style="font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--dim);margin:8px 0 2px">Verified payees</div>
      ${m.beneficiaries.map((b) => `<div class="payee"><span class="vbadge">✓</span><span>${esc(b.name || `#${b.id}`)}</span><span class="mono" style="color:var(--dim);font-size:11.5px">${short(b.wallet)}</span></div>`).join("")}
    </div>`;
}

function renderEvents() {
  const names = Object.fromEntries(S.data.mandate.beneficiaries.map((b) => [b.id, b.name]));
  $("#events").innerHTML = S.data.events
    .map((e) => {
      if (e.type === "settled") {
        return `<div class="event settled">
          <span class="kind">Settled</span>
          <span class="desc">${esc(names[e.beneficiaryId] || "Payee #" + e.beneficiaryId)} · ${short(e.payee)}${e.approvedByOwner ? " · owner co-signed" : ""} · <a class="txlink" href="${EXPLORER}/tx/${e.txHash}" target="_blank" rel="noopener">${short(e.txHash)} ↗</a></span>
          <span class="amt">${fmt(e.amount)}</span></div>`;
      }
      return `<div class="event refused">
        <span class="kind">Refused</span>
        <span class="desc">${esc(REASONS[e.reason] || "Reason " + e.reason)} · <a class="txlink" href="${EXPLORER}/tx/${e.txHash}" target="_blank" rel="noopener">${short(e.txHash)} ↗</a></span>
        <span class="amt">${fmt(e.amount)}</span></div>`;
    })
    .join("");
}

function renderPanel(animate = false) {
  const panel = $("#agentPanel");
  if (S.timer) clearTimeout(S.timer);
  const c = S.data.cases.find((x) => keyOf(x) === S.selected);
  if (!c) {
    panel.innerHTML = `<div class="agent-body"><p class="muted">Select an invoice.</p></div>`;
    return;
  }
  const st = STATUS[c.status] || STATUS.pending;
  const dec = c.decision || { checks: [], decision: "pending", reasonLabel: "PENDING" };
  const verdict = {
    pay: { cls: "pay", glyph: "✓", big: "Inside the mandate", small: "The agent can settle this invoice without asking." },
    needs_approval: { cls: "needs_approval", glyph: "!", big: "Owner approval required", small: `${fmt(c.amount * 1e6)} is above the ${fmt(S.data.mandate.policy.approvalThreshold)} approval line.` },
    refuse: { cls: "refuse", glyph: "✕", big: "Refused by the agent", small: REASONS[dec.reason] || dec.reasonLabel },
  }[dec.decision] || { cls: "needs_approval", glyph: "·", big: "Not processed", small: "" };

  panel.innerHTML = `
    <div class="agent-head">
      <div style="flex:1">
        <div class="amount">${fmt(Number(c.amount) * 1e6)} <span style="font-size:13px;color:var(--muted)">tUSD8</span></div>
        <div class="who">${esc(c.meta?.subject || c.id)}</div>
      </div>
      <span class="chip ${st.cls}">${st.label}</span>
    </div>
    <div class="agent-body">
      <div class="invoice-grid">
        <div class="kv"><div class="k">Payee</div><div class="v">${esc(c.issuer.name)}</div></div>
        <div class="kv"><div class="k">Payout wallet</div><div class="v mono">${short(c.issuer.wallet)}</div></div>
        <div class="kv"><div class="k">Invoice</div><div class="v mono">${esc(c.id)}</div></div>
        <div class="kv"><div class="k">Memo</div><div class="v">${esc(c.memo)}</div></div>
        <div class="kv"><div class="k">Sender</div><div class="v">${esc(c.meta?.from || "—")}</div></div>
        <div class="kv"><div class="k">Due</div><div class="v">${date(c.dueAt)}</div></div>
      </div>
      ${c.meta?.note ? `<p class="note" style="margin:-6px 0 10px">⚠ ${esc(c.meta.note)}</p>` : ""}
      <div class="checks" id="checks">
        ${dec.checks.map((k) => `
          <div class="check ${k.status}">
            <span class="ico">${k.status === "pass" ? "✓" : k.status === "fail" ? "✕" : "!"}</span>
            <span><span class="t">${esc(k.label)}</span><br><span class="d">${esc(k.detail)}</span></span>
          </div>`).join("")}
      </div>
      <div id="verdict"></div>
      <div class="agent-actions" id="actions"></div>
      <p class="note">${dec.checks.length} checks · the same rules are re-run by <code>pay()</code> on Aevum, so a buggy agent cannot talk its way past them.</p>
    </div>`;

  const showVerdict = () => {
    $("#verdict").innerHTML = dec.decision === "pending" ? "" : `
      <div class="decision ${verdict.cls}">
        <span class="glyph">${verdict.glyph}</span>
        <div><div class="big">${verdict.big}</div><div class="small">${esc(verdict.small)}</div></div>
      </div>`;
    renderActions(c);
  };

  if (animate) {
    const rows = [...panel.querySelectorAll(".check")];
    rows.forEach((r) => r.classList.remove("shown"));
    rows.forEach((r, i) => setTimeout(() => r.classList.add("shown"), 120 * i));
    S.timer = setTimeout(showVerdict, 120 * rows.length + 120);
  } else {
    panel.querySelectorAll(".check").forEach((r) => r.classList.add("shown"));
    showVerdict();
  }
}

function renderActions(c) {
  const wrap = $("#actions");
  const parts = [];
  if (c.txHash) {
    parts.push(`<a class="txlink" href="${EXPLORER}/tx/${c.txHash}" target="_blank" rel="noopener">${c.txHash.slice(0, 18)}… ↗</a>`);
  }
  parts.push(`<button class="btn small" id="replayOne">Replay decision</button>`);
  if (S.api) {
    if (c.status === "pending") parts.push(`<button class="btn small primary" id="runBtn">Run the agent</button>`);
    if (c.status === "needs_approval") parts.push(`<button class="btn small primary" id="approveBtn">Owner co-signs</button>`);
  }
  wrap.innerHTML = parts.join("");
  $("#replayOne").onclick = () => renderPanel(true);
  if ($("#runBtn")) $("#runBtn").onclick = () => runLive(keyOf(c), false);
  if ($("#approveBtn")) $("#approveBtn").onclick = () => runLive(keyOf(c), true);
}

async function runLive(caseId, approve) {
  if (S.busy) return;
  S.busy = true;
  const btn = approve ? $("#approveBtn") : $("#runBtn");
  if (btn) { btn.disabled = true; btn.textContent = approve ? "Owner signing…" : "Agent working…"; }
  try {
    const res = await fetch(`api/run/${encodeURIComponent(caseId)}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approve }),
    });
    const out = await res.json();
    if (!res.ok) throw new Error(out.error || "run failed");
    S.data = await (await fetch("api/state", { cache: "no-store" })).json();
    render();
    renderPanel(true);
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = "Retry"; }
    $("#actions").insertAdjacentHTML("beforeend", `<span class="note" style="color:var(--red)">${esc(err.message)}</span>`);
  } finally {
    S.busy = false;
  }
}

/* Read live state straight from Aevum with plain JSON-RPC (no wallet, no library). */
async function rpc(method, params) {
  const res = await fetch(S.data.network.rpc, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  const body = await res.json();
  if (body.error) throw new Error(body.error.message || "rpc error");
  return body.result;
}

async function liveProbe() {
  const m = S.data.mandate;
  const pad = (addr) => addr.toLowerCase().replace(/^0x/, "").padStart(64, "0");
  try {
    const [bal, remaining] = await Promise.all([
      rpc("eth_call", [{ to: m.token, data: "0x70a08231" + pad(m.address) }, "latest"]),
      rpc("eth_call", [{ to: m.address, data: "0xfc3c5515" }, "latest"]),
    ]);
    const el = document.querySelector('[data-live="balance"]');
    if (el) el.innerHTML = `${fmt(parseInt(bal, 16))}<small>tUSD8</small>`;
    const chip = $("#remainingChip");
    if (chip) chip.textContent = `${fmt(parseInt(remaining, 16))} tUSD8 left today · live`;
    $("#liveBadge").textContent = "live · Aevum RPC";
    $("#liveBadge").classList.add("live");
  } catch (err) {
    const el = document.querySelector('[data-live="balance"]');
    if (el) el.title = "live read failed: " + err.message;
  }
}

$("#replayAll").addEventListener("click", async () => {
  for (const c of S.data.cases) {
    S.selected = keyOf(c);
    renderCases();
    renderPanel(true);
    await new Promise((r) => setTimeout(r, 1800));
  }
});

boot().catch((err) => {
  document.body.insertAdjacentHTML("afterbegin", `<pre style="color:#ff6b6b;padding:20px">${esc(err.stack || err)}</pre>`);
});
