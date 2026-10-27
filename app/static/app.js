/* Private Accounting: local UI. No remote resources, telemetry, or automatic model requests. */
"use strict";
(() => {
  const $ = (selector, scope = document) => scope.querySelector(selector);
  const NS = "http://www.w3.org/2000/svg";
  const paths = {
    grid: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"],
    arrows: ["M4 7h15m-4-4 4 4-4 4", "M20 17H5m4-4-4 4 4 4"],
    plan: ["M4 20V10m8 10V4m8 16v-7", "M2 20h20"],
    plus: ["M12 5v14M5 12h14"],
    check: ["m5 12 4 4L19 6"],
    review: ["M9 4H5v17h14V4h-4", "M9 2h6v5H9z", "m8 14 3 3 5-6"],
    folder: ["M3 7h7l2-3h9v15H3z", "M3 7V4h6l3 3"],
    settings: ["M4 6h16M4 12h16M4 18h16", "M8 3v6m8 0v6M9 15v6"],
    calendar: ["M4 5h16v16H4zM4 10h16M8 3v4m8-4v4"],
    up: ["M5 17 19 3M8 3h11v11"],
    down: ["M5 7 19 21M8 21h11V10"],
    wallet: ["M3 6h17v15H3zM3 6V3h14v3", "M15 11h6v5h-6z"],
    shield: ["m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z", "m8 12 3 3 5-6"],
    info: ["M12 11v6M12 7h.01", "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0"],
    file: ["M5 3h9l5 5v13H5zM14 3v6h5M8 13h8m-8 4h5"],
    download: ["M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"],
    upload: ["M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5"],
    spark: ["m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8z"],
    note: ["M4 3h16v18H4zM8 8h8M8 12h8m-8 4h5"],
    clock: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M12 7v5l3 2"],
    home: ["m3 10 9-7 9 7M5 9v12h14V9M9 21v-8h6v8"],
    bag: ["M4 8h16l-1 13H5zM8 8V6a4 4 0 0 1 8 0v2"],
    arrow: ["M4 12h16m-6-6 6 6-6 6"],
    stop: ["M7 3h10l4 4v10l-4 4H7l-4-4V7z", "M9 9h6v6H9z"],
    help: ["M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0", "M9 8a3 3 0 0 1 6 1c0 2-3 2-3 4m0 4h.01"]
  };
  function icon(name, className = "") {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", `icon ${className}`); svg.setAttribute("aria-hidden", "true");
    (paths[name] || paths.file).forEach(d => { const p = document.createElementNS(NS, "path"); p.setAttribute("d", d); svg.append(p); });
    return svg;
  }
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (value == null || value === false) return;
      if (key === "class") node.className = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (["checked", "disabled", "required", "multiple", "selected"].includes(key)) node[key] = !!value;
      else if (key === "value") node.value = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    });
    const append = child => { if (Array.isArray(child)) child.forEach(append); else if (child != null && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child))); };
    children.forEach(append); return node;
  }
  const now = new Date();
  const dateLocal = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const today = dateLocal(now);
  const defaultStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const defaultEnd = dateLocal(new Date(now.getFullYear(), now.getMonth() + 1, 0));
  const app = {
    page: "dashboard", addTab: "manual", snapshot: null, welcomed: false, previews: [], modelStatus: null,
    drafts: { transaction: {}, setup: {}, notes: "", model: "", executable: "", documentIds: new Set() },
    filters: { query: "", classification: "", start: "", end: "" }, analysis: null, analysisBusy: false,
    connected: true, pendingForms: 0, reviewBusy: false
  };
  let token = "";
  try {
    const fragment = location.hash.slice(1);
    if (fragment) {
      const values = new URLSearchParams(fragment);
      token = values.get("token") || values.get("access_token") || (!fragment.includes("=") && fragment !== "dashboard" ? decodeURIComponent(fragment) : "");
      history.replaceState(null, "", location.pathname + location.search);
      if (token) sessionStorage.setItem("private-accounting-token", token);
    }
    token = token || sessionStorage.getItem("private-accounting-token") || "";
  } catch (_) { /* A browser may restrict session storage. This tab still retains its token in memory. */ }
  async function api(path, body, timeout = 45000) {
    const url = new URL(path, location.origin);
    if (url.origin !== location.origin) throw new Error("This workspace only connects to its own local service.");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, { method: body === undefined ? "GET" : "POST", headers: { "Authorization": `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, credentials: "same-origin", cache: "no-store" });
      const contentType = response.headers.get("content-type") || "";
      const result = contentType.includes("json") ? await response.json() : { error: await response.text() };
      if (!response.ok) {
        const detail = result.error || result.detail || result.message || `Request failed (${response.status}).`;
        const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail)); error.status = response.status; throw error;
      }
      return result;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("This request timed out. Nothing was retried automatically. Refresh the saved records before trying again.");
      if (error instanceof TypeError) throw new Error("The local service could not be reached. Check that the launcher is still running, then refresh.");
      throw error;
    } finally { clearTimeout(timer); }
  }
  const state = () => app.snapshot?.state || {};
  const overview = () => app.snapshot?.overview || {};
  const transactions = () => Array.isArray(state().transactions) ? state().transactions : [];
  const documents = () => Array.isArray(app.snapshot?.documents) ? app.snapshot.documents : [];
  const proposals = () => (Array.isArray(app.snapshot?.proposals) ? app.snapshot.proposals : []).filter(p => !p.status || ["pending", "proposed", "draft"].includes(p.status));
  const number = value => { const n = Number(value); return Number.isFinite(n) ? n : 0; };
  const money = value => {
    if (value === null || value === undefined || value === "") return "Unknown";
    const valid = typeof value === "number" ? Number.isFinite(value) : typeof value === "string" && /^-?\d+(?:\.\d{1,2})?$/.test(value);
    if (!valid) return `Unresolved: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`;
    if (typeof value === "string") {
      const negative = value.startsWith("-"); const [whole, fraction = ""] = (negative ? value.slice(1) : value).split(".");
      return `${negative ? "-" : ""}$${whole.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction.padEnd(2, "0")}`;
    }
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 }).format(Number(value));
  };
  const prettyDate = value => { if (!value) return "Not provided"; const d = new Date(`${String(value).slice(0, 10)}T12:00:00`); return Number.isNaN(d.valueOf()) ? String(value) : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }); };
  const shortDate = value => { if (!value) return "—"; const d = new Date(`${String(value).slice(0, 10)}T12:00:00`); return Number.isNaN(d.valueOf()) ? String(value) : d.toLocaleDateString("en-US", { month: "short", day: "numeric" }); };
  const humanize = text => String(text || "unclassified").replace(/_/g, " ").replace(/^./, s => s.toUpperCase());
  const setup = () => ({ start_date: defaultStart, end_date: defaultEnd, goals: "", currency: "USD", ...state().setup });
  function toast(message, error = false) {
    if (!error) $("#toast-stack").querySelectorAll(".toast:not(.error)").forEach(item => item.remove());
    while ($("#toast-stack").children.length >= 3) $("#toast-stack").firstElementChild.remove();
    const item = el("div", { class: `toast${error ? " error" : ""}`, role: error ? "alert" : "status" }, el("span", {}, message));
    item.append(el("button", { type: "button", "aria-label": "Dismiss notification", onclick: () => item.remove() }, "×"));
    $("#toast-stack").append(item); setTimeout(() => item.remove(), error ? 15000 : 6500);
  }
  function button(label, handler, { variant = "", glyph, small = false, title, disabled = false } = {}) {
    const b = el("button", { type: "button", class: `button ${variant} ${small ? "small" : ""}`, title, disabled }, glyph ? icon(glyph) : null, label);
    b.addEventListener("click", async () => {
      if (b.dataset.busy) return;
      b.dataset.busy = "1"; b.disabled = true;
      try { await handler(b); } catch (error) { toast(error.message || "The action could not be completed.", true); }
      finally { delete b.dataset.busy; b.disabled = false; }
    }); return b;
  }
  function heading(eyebrow, title, subtitle, action) {
    return el("div", { class: "page-heading" }, el("div", {}, el("div", { class: "eyebrow" }, eyebrow), el("h1", {}, title), el("p", {}, subtitle)), action);
  }
  function badge(text, variant = "") { return el("span", { class: `badge ${variant}` }, text); }
  function card(title, subtitle, body, action, footer) {
    return el("section", { class: "card" }, title ? el("div", { class: "card-header" }, el("div", {}, el("h2", {}, title), subtitle ? el("p", {}, subtitle) : null), action) : null, body, footer ? el("div", { class: "card-footer" }, icon("info"), footer) : null);
  }
  function empty(title, copy, glyph = "file", action, compact = false) {
    return el("div", { class: `empty-state ${compact ? "compact" : ""}` }, el("div", { class: "empty-icon" }, icon(glyph)), el("h3", {}, title), el("p", {}, copy), action);
  }
  function note(copy, glyph = "info") { return el("div", { class: "panel-note" }, icon(glyph), el("span", {}, copy)); }
  function notice(title, copy, action, variant = "") { return el("div", { class: `notice ${variant}` }, icon("info"), el("div", { class: "notice-text" }, el("strong", {}, title), copy ? el("p", {}, copy) : null), action); }
  function field(label, name, type = "text", value = "", options = {}) {
    const id = `${options.prefix || "field"}-${name}-${Math.random().toString(36).slice(2, 7)}`;
    const control = type === "textarea" ? el("textarea", { id, name, rows: options.rows || 4 }) : type === "select" ? el("select", { id, name }, (options.choices || []).map(choice => el("option", { value: typeof choice === "string" ? choice : choice.value }, typeof choice === "string" ? humanize(choice) : choice.label))) : el("input", { id, name, type });
    if (type === "select" && value != null && value !== "" && ![...control.options].some(option => option.value === String(value))) control.append(el("option", { value: String(value) }, `Unresolved: ${String(value)}`));
    control.value = value ?? "";
    ["required", "placeholder", "min", "max", "step", "maxlength", "autocomplete", "accept"].forEach(key => { if (options[key] != null) control.setAttribute(key, options[key] === true ? "" : options[key]); });
    if (options.oninput) control.addEventListener("input", options.oninput);
    if (options.onchange) control.addEventListener("change", options.onchange);
    if (options.help) control.setAttribute("aria-describedby", `${id}-help`);
    const container = el("div", { class: `field ${options.full ? "full-width" : ""}` }, el("label", { for: id }, label), control, options.help ? el("p", { class: "field-help", id: `${id}-help` }, options.help) : null);
    return container;
  }
  function submitForm(form, handler) {
    form.addEventListener("submit", async event => {
      event.preventDefault(); if (!form.reportValidity()) return;
      const b = $("button[type=submit]", form); if (b.disabled) return;
      const values = Object.fromEntries(new FormData(form).entries());
      const controls = [...form.querySelectorAll("input, select, textarea, button")].map(control => [control, control.disabled]);
      controls.forEach(([control]) => { control.disabled = true; });
      app.pendingForms++; syncPendingUI(); form.setAttribute("aria-busy", "true");
      const spin = el("span", { class: "spinner", "aria-hidden": "true" }); b.prepend(spin);
      try { await handler(values); } catch (error) { toast(error.message, true); }
      finally { app.pendingForms--; syncPendingUI(); form.removeAttribute("aria-busy"); spin.remove(); controls.forEach(([control, disabled]) => { control.disabled = disabled; }); }
    });
  }
  function submitButton(text) { return el("button", { class: "button", type: "submit" }, icon("review"), text); }
  function openDialog(title, subtitle, body, { dirtyGuard = true } = {}) {
    const dialog = $("#app-dialog");
    if (dialog.open) dialog.close();
    dialog.replaceChildren(el("div", { class: "dialog-header" }, el("div", {}, el("h2", { id: "dialog-title" }, title), subtitle ? el("p", {}, subtitle) : null), el("button", { type: "button", class: "icon-button", "aria-label": "Close dialog", onclick: () => tryClose() }, "×")), el("div", { class: "dialog-body" }, body));
    dialog.dataset.dirty = "";
    const tryClose = () => { if (pendingAction()) return; if (!dirtyGuard || !dialog.dataset.dirty || confirm("Close this form? Changes in this form have not been proposed for review.")) dialog.close(); };
    dialog.oncancel = event => { event.preventDefault(); tryClose(); };
    dialog.oninput = () => { dialog.dataset.dirty = "1"; };
    dialog.showModal(); return dialog;
  }
  function closeDialog() { $("#app-dialog").close(); }
  async function refresh({ rerender = true } = {}) {
    const snapshot = await api("/api/state"); app.snapshot = snapshot; app.connected = true;
    $("#connection-status").replaceChildren(el("span", { class: "status-dot" }), "On this computer");
    renderNavigation(); if (rerender) renderPage(); return snapshot;
  }
  const pages = [ ["dashboard", "Dashboard", "grid"], ["transactions", "Transactions", "arrows"], ["plans", "Plans & debts", "plan"], ["add", "Add information", "plus"], ["review", "Review", "review"], ["files", "Files & exports", "folder"] ];
  function pendingAction() {
    if (!app.pendingForms && !app.reviewBusy) return false;
    toast("Wait for the current review request to finish. Your form remains available if it fails.", true); return true;
  }
  function syncPendingUI() {
    const pending = !!(app.pendingForms || app.reviewBusy);
    document.querySelectorAll("#navigation button, .sidebar-help, #refresh-button, .tab").forEach(control => { control.disabled = pending; });
    $("#main").setAttribute("aria-busy", String(pending));
  }
  function renderNavigation() {
    $("#navigation").replaceChildren(...pages.map(([id, label, glyph]) => el("button", { type: "button", class: `nav-item${app.page === id ? " active" : ""}`, "aria-label": label, "aria-current": app.page === id ? "page" : null, onclick: () => navigate(id) }, icon(glyph), label, id === "review" && proposals().length ? el("span", { class: "nav-count", "aria-label": `${proposals().length} pending changes` }, proposals().length) : null)));
    $("#page-label").textContent = pages.find(p => p[0] === app.page)?.[1] || "Settings & help";
    $(".sidebar-help").setAttribute("aria-current", app.page === "settings" ? "page" : "false");
    syncPendingUI();
  }
  function navigate(page, options = {}) {
    if (!options.afterSubmit && pendingAction()) return;
    app.page = page; if (options.tab) app.addTab = options.tab;
    $("#sidebar").classList.remove("open"); syncSidebar();
    renderNavigation(); renderPage({ force: options.afterSubmit }); $("#main").focus({ preventScroll: true }); window.scrollTo({ top: 0 });
    if (page === "add" && app.addTab === "notes") loadModelStatus();
  }
  function renderPage({ force = false } = {}) {
    if (!app.snapshot || (!force && (app.pendingForms || app.reviewBusy))) return;
    const renderers = { dashboard: renderDashboard, transactions: renderTransactions, plans: renderPlans, add: renderAdd, review: renderReview, files: renderFiles, settings: renderSettings };
    $("#main").replaceChildren((renderers[app.page] || renderDashboard)());
    syncPendingUI();
  }
  async function propose(kind, data) {
    const result = await api("/api/propose", { kind, data }); await refresh({ rerender: false });
    navigate("review", { afterSubmit: true }); toast("Your proposed change is ready to review. Nothing has been saved yet."); return result;
  }
  function dateInPeriod(t) { return (!overview().start_date || t.date >= overview().start_date) && (!overview().end_date || t.date <= overview().end_date); }
  function renderDashboard() {
    const root = el("div"); const o = overview(); const totals = o.totals || {}; const txs = transactions().filter(dateInPeriod);
    root.append(heading("A little clarity, every day", "Your money, in perspective.", "A calm place to understand what comes in, what goes out, and what comes next.", button("Add information", () => navigate("add"), { glyph: "plus" })));
    if (proposals().length) root.append(notice(`${proposals().length} ${proposals().length === 1 ? "change is" : "changes are"} waiting for you`, "Review proposed information before it becomes part of your records.", button("Review changes", () => navigate("review"), { variant: "secondary", small: true })));
    root.append(el("div", { class: "period-bar" }, el("div", { class: "period-label" }, icon("calendar"), (o.start_date && o.end_date ? `${prettyDate(o.start_date)} — ${prettyDate(o.end_date)}` : o.start_date ? `From ${prettyDate(o.start_date)}` : o.end_date ? `Through ${prettyDate(o.end_date)}` : "All approved dates"), button("Change", () => navigate("settings"), { variant: "tertiary", small: true })), el("span", { class: "subtle" }, `${o.transaction_count ?? txs.length} approved ${(o.transaction_count ?? txs.length) === 1 ? "transaction" : "transactions"} · USD`)));
    const metric = (label, value, caption, glyph, featured = false) => el("section", { class: `metric-card${featured ? " featured" : ""}`, "aria-label": label }, el("div", { class: "metric-top" }, label, icon(glyph)), el("div", { class: `metric-value${number(value) < 0 ? " negative" : ""}` }, money(value)), el("div", { class: "metric-caption" }, caption));
    root.append(el("div", { class: "metric-grid" }, metric("Income", totals.income, "Recorded income in this period", "up"), metric("Expenses", totals.expenses, "Recorded expenses in this period", "down"), metric("Income minus expenses", totals.net_income_expenses, "Before transfers, loans, and refunds", "wallet", true)));
    if (!transactions().length) root.append(el("div", { class: "first-steps" }, [["1", "Start with what you know", "Add an entry, a local file, or your notes."], ["2", "Make it yours", "Review the details and resolve missing information."], ["3", "See the picture emerge", "Approve records to update this overview."]].map(([n, title, copy]) => el("div", { class: "step-card" }, el("span", { class: "step-number" }, n), el("div", {}, el("h3", {}, title), el("p", {}, copy))))));
    const spending = (o.categories || []).filter(c => number(c.expenses) > 0).sort((a, b) => number(b.expenses) - number(a.expenses));
    const colors = ["#3e7a68", "#809b73", "#b8c79c", "#b2a785", "#8ea7a5", "#c7cebf"];
    const categoryBody = spending.length ? el("div", { class: "category-list" }, spending.slice(0, 6).map((c, i) => el("div", {}, el("div", { class: "category-line" }, el("span", { class: "category-name" }, el("span", { class: "category-dot", style: `background:${colors[i]}` }), c.category || "Uncategorized"), el("span", { class: "category-amount" }, money(c.expenses))), el("div", { class: "progress-track", role: "img", "aria-label": `${c.category}: ${money(c.expenses)}` }, el("div", { class: "progress-fill", style: `width:${Math.max(1, number(c.expenses) / Math.max(1, number(totals.expenses)) * 100)}%;background:${colors[i]}` }))))) : empty("Your spending story starts here", "Approved expenses will appear by category, so you can see where your money goes.", "bag", null, true);
    root.append(el("div", { class: "dashboard-columns" }, card("Income & expenses", "Approved records across your selected period", txs.length ? cashChart(txs) : empty("No chart without your records", "Add your first income or expense to build a picture based on your information.", "plan", button("Add your first entry", () => navigate("add"), { variant: "secondary", small: true }), true), null, "Transfers, loans, refunds, and unclassified entries are shown separately."), card("Where it went", "Expenses by category", categoryBody, spending.length ? button("View all", () => { app.filters.classification = "expense"; navigate("transactions"); }, { variant: "tertiary", small: true }) : null)));
    root.append(card("Recent transactions", "A few of your latest approved records", txs.length ? transactionTable([...txs].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 5), false) : empty("A fresh start", "Your transactions will appear here after you review and approve them.", "arrows"), button("View all transactions", () => navigate("transactions"), { variant: "tertiary", small: true }), txs.length ? `${money(totals.net_cash_flow)} net cash movement in this period. This is not an account balance.` : null));
    if (txs.length) root.append(el("div", { class: "section-gap" }, card("Other cash movements", "Signed totals, kept separate from income and expenses.", el("div", { class: "card-body" }, el("div", { class: "movement-grid" }, [["Net transfers", totals.transfers], ["Loan cash movement", totals.loans], ["Refunds", totals.refunds], ["Unclassified", totals.unclassified]].map(([label, value]) => el("div", {}, el("div", { class: "detail-label" }, label), el("div", { class: "movement-value" }, money(value)))))), null, "Account balances and net worth are unknown without complete balance information.")));
    if ((o.review?.unclassified_count || 0) > 0) root.append(el("div", { class: "section-gap" }, notice(`${o.review.unclassified_count} ${o.review.unclassified_count === 1 ? "entry needs" : "entries need"} a classification`, "Unclassified entries affect cash movement but are not counted as income or expenses.", button("Take a look", () => { app.filters.classification = "unclassified"; navigate("transactions"); }, { variant: "secondary", small: true }))));
    return root;
  }
  function cashChart(txs) {
    const grouped = new Map();
    txs.forEach(t => { if (!["income", "expense"].includes(t.classification)) return; const key = String(t.date).slice(0, 7); const g = grouped.get(key) || { income: 0, expense: 0 }; g[t.classification] += Math.abs(number(t.amount)); grouped.set(key, g); });
    const months = [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(-12);
    if (!months.length) return empty("No income or expenses in this period", "Transfers and other cash movements remain visible in your transactions.", "plan", null, true);
    const svg = document.createElementNS(NS, "svg"); svg.setAttribute("class", "chart-svg"); svg.setAttribute("viewBox", "0 0 510 190"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Monthly approved income and expenses. Exact values are listed below the chart.");
    const max = Math.max(...months.flatMap(([, g]) => [g.income, g.expense]), 1); const width = 440 / months.length;
    const svgEl = (tag, attrs, text) => { const n = document.createElementNS(NS, tag); Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v)); if (text != null) n.textContent = text; svg.append(n); return n; };
    [0, .5, 1].forEach(tick => { const y = 150 - tick * 130; svgEl("line", { x1: 58, x2: 505, y1: y, y2: y, stroke: "#edf1e8", "stroke-dasharray": "3 4" }); svgEl("text", { x: 49, y: y + 4, "text-anchor": "end", class: "chart-label" }, new Intl.NumberFormat("en-US", { notation: "compact", style: "currency", currency: "USD", maximumFractionDigits: 1 }).format(max * tick)); });
    months.forEach(([month, g], i) => {
      const x = 60 + width * i + width / 2; const bar = Math.min(24, width * .25);
      [[g.income, "#427e6e", x - bar - 2], [g.expense, "#c7d3b6", x + 2]].forEach(([v, fill, left]) => svgEl("rect", { x: left, y: 150 - v / max * 130, width: bar, height: Math.max(v ? 2 : 0, v / max * 130), fill, rx: 3 }));
      svgEl("text", { x, y: 176, "text-anchor": "middle", class: "chart-label" }, new Date(`${month}-15T12:00:00`).toLocaleDateString("en-US", { month: "short", ...(months.length > 6 ? {} : { year: "2-digit" }) }));
    });
    return el("div", { class: "chart" }, svg, el("div", { class: "chart-legend" }, el("span", {}, el("span", { class: "legend-dot income" }), "Income"), el("span", {}, el("span", { class: "legend-dot expense" }), "Expenses")), el("details", { class: "chart-note" }, el("summary", {}, "View exact chart values"), el("div", {}, months.map(([month, g]) => el("p", {}, `${month}: income ${money(g.income)} · expenses ${money(g.expense)}`)))));
  }
  function transactionTable(rows, withActions = true) {
    rows = rows.map(row => row && typeof row === "object" && !Array.isArray(row) ? row : { description: `Unresolved row: ${JSON.stringify(row)}`, amount: null, classification: "unclassified" });
    const table = el("table", { class: "data-table" }, el("thead", {}, el("tr", {}, ["Transaction", "Date", "Category", "Type", "Amount", ...(withActions ? ["Actions"] : [])].map((title, i) => el("th", { scope: "col", class: i === 4 ? "amount" : "" }, title)))));
    table.append(el("tbody", {}, rows.map(t => el("tr", {}, el("td", {}, el("div", { class: "table-entity" }, el("span", { class: "entity-icon" }, icon(t.classification === "income" ? "up" : t.classification === "transfer" ? "arrows" : "bag")), el("span", {}, el("span", { class: "table-title" }, t.description || "No description"), el("span", { class: "table-subtitle", title: `${t.account || "Account not provided"} · ${t.source || "Source not provided"}` }, `${t.account || "Account not provided"} · ${t.source || "Source not provided"}`)))), el("td", { class: "cell-nowrap", title: prettyDate(t.date) }, shortDate(t.date)), el("td", {}, t.category || "Uncategorized"), el("td", {}, badge(humanize(t.classification), t.classification === "unclassified" ? "warning" : "neutral")), el("td", { class: `amount ${number(t.amount) > 0 ? "positive" : "negative"}` }, `${number(t.amount) > 0 ? "+" : ""}${money(t.amount)}`), withActions ? el("td", {}, el("div", { class: "row-actions" }, el("button", { class: "text-button", type: "button", onclick: () => transactionDialog(t), "aria-label": `Edit ${t.description || "transaction"}` }, "Edit"), el("button", { class: "text-button danger", type: "button", onclick: async () => { if (confirm(`Propose deleting “${t.description || "this transaction"}” (${money(t.amount)})? You will review the deletion before it is saved.`)) { try { await propose("delete_transaction", { id: t.id }); } catch (e) { toast(e.message, true); } } }, "aria-label": `Delete ${t.description || "transaction"}` }, "Delete"))) : null))));
    return el("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": "Transactions" }, table);
  }
  function renderTransactions() {
    const root = el("div", {}, heading("The details that add up", "Your transactions.", "Search, check, and refine the records behind your overview.", button("Add an entry", () => navigate("add"), { glyph: "plus" })));
    const content = el("div");
    const update = () => {
      const f = app.filters; const q = f.query.trim().toLowerCase();
      const rows = [...transactions()].filter(t => (!q || [t.description, t.account, t.category, t.source].some(v => String(v || "").toLowerCase().includes(q))) && (!f.classification || t.classification === f.classification) && (!f.start || t.date >= f.start) && (!f.end || t.date <= f.end)).sort((a, b) => String(b.date).localeCompare(String(a.date)));
      content.replaceChildren(rows.length ? transactionTable(rows) : empty(transactions().length ? "No matching transactions" : "Your records begin here", transactions().length ? "Try another search or clear the filters to see all your approved records." : "Add an entry or preview a local file. Every change passes through your review.", "arrows", transactions().length ? button("Clear filters", () => { app.filters = { query: "", classification: "", start: "", end: "" }; renderPage(); }, { variant: "secondary", small: true }) : button("Add information", () => navigate("add"), { variant: "secondary", small: true })), el("div", { class: "table-bottom" }, el("span", {}, `${rows.length} of ${transactions().length} approved records`), el("span", {}, "All dates unless filtered · USD")));
    };
    const filters = el("div", { class: "filters" }, field("Search records", "search", "search", app.filters.query, { placeholder: "Description, account, category…", oninput: e => { app.filters.query = e.target.value; update(); } }), field("Type", "type", "select", app.filters.classification, { choices: [{ value: "", label: "All types" }, "income", "expense", "transfer", "loan", "refund", "unclassified"], onchange: e => { app.filters.classification = e.target.value; update(); } }), field("From", "from", "date", app.filters.start, { onchange: e => { app.filters.start = e.target.value; update(); } }), field("Through", "through", "date", app.filters.end, { onchange: e => { app.filters.end = e.target.value; update(); } }));
    filters.firstElementChild.classList.add("search-field"); root.append(card(null, null, el("div", {}, filters, content))); update();
    root.append(el("div", { class: "section-gap" }, note("Amounts are signed: positive means money came in; negative means money went out. A transaction’s type determines which totals it contributes to.")));
    return root;
  }
  function transactionForm(initial = {}, editing = false, inDialog = false) {
    const data = { date: "", description: "", amount: "", account: "", classification: "unclassified", category: "", source: "Manual entry", ...initial };
    const form = el("form"); const saveDraft = e => { if (!editing) app.drafts.transaction[e.target.name] = e.target.value; };
    const grid = el("div", { class: "form-grid" }, field("Date", "date", "date", data.date, { required: true, oninput: saveDraft }), field("Amount (USD, signed)", "amount", "number", data.amount, { required: true, step: "0.01", placeholder: "−45.00 or 2,500.00", help: "Use a minus sign for money going out.", oninput: saveDraft }), field("Description", "description", "text", data.description, { required: true, full: true, maxlength: 500, placeholder: "What was this for?", oninput: saveDraft }), field("Account", "account", "text", data.account, { placeholder: "e.g. Checking, cash, credit card", required: true, maxlength: 120, oninput: saveDraft }), field("Type", "classification", "select", data.classification, { choices: ["unclassified", "income", "expense", "transfer", "loan", "refund"], oninput: saveDraft }), field("Category", "category", "text", data.category, { placeholder: "e.g. Groceries, salary, housing", maxlength: 120, oninput: saveDraft }), field("Source or reference", "source", "text", data.source, { placeholder: "Where did this information come from?", maxlength: 300, oninput: saveDraft }));
    form.append(grid, note("Choose “Unclassified” if you are unsure. You can refine it later; the app will not guess for you."), el("div", { class: "form-actions" }, el("span", { class: "subtle" }, "You’ll review this before saving."), submitButton(editing ? "Review my changes" : "Review this entry")));
    submitForm(form, async values => { if (editing) values.id = data.id; if (!values.category.trim()) values.category = "Uncategorized"; await propose("transaction", values); if (!editing) app.drafts.transaction = {}; if (inDialog) closeDialog(); }); return form;
  }
  function transactionDialog(t) { openDialog("Edit transaction", "Changes will remain a proposal until you approve them.", transactionForm(t, true, true)); }
  function renderPlans() {
    const o = overview(); const budgets = Array.isArray(o.budgets) ? o.budgets : state().budgets || []; const debts = Array.isArray(o.debts) ? o.debts : state().debts || [];
    const root = el("div", {}, heading("Looking ahead", "Plans with a little breathing room.", "Set spending intentions and keep a clear record of what you owe."));
    const budgetBody = budgets.length ? el("div", { class: "mt-12" }, budgets.map(b => { const pct = number(b.amount) > 0 ? number(b.actual) / number(b.amount) * 100 : 0; return el("div", { class: "budget-row" }, el("div", { class: "budget-row-top" }, el("strong", {}, b.category), el("span", { class: "budget-amount" }, `${b.actual == null ? "Unknown spending" : money(b.actual)} of ${b.amount == null ? "unknown plan" : money(b.amount)}`)), el("div", { class: "progress-track", role: "img", "aria-label": `${money(b.actual)} spent of ${money(b.amount)} planned` }, el("div", { class: "progress-fill", style: `width:${Math.max(0, Math.min(pct, 100))}%;background:${pct > 100 ? "#b48562" : "#4d826c"}` })), el("div", { class: "budget-row-bottom" }, el("span", {}, `${shortDate(b.start_date)} — ${shortDate(b.end_date)}`), el("span", {}, b.remaining == null ? "Remaining amount unknown" : number(b.remaining) < 0 ? `${money(Math.abs(number(b.remaining)))} over plan` : `${money(b.remaining)} remaining`))); })) : empty("Make room for what matters", "Set a category and an amount. Approved expenses within the plan’s dates show your progress.", "plan", button("Create your first plan", () => budgetDialog(), { variant: "secondary", small: true }), true);
    const debtBody = debts.length ? el("div", { class: "mt-12" }, debts.map(d => el("div", { class: "debt-row" }, el("h3", {}, d.label), el("div", { class: "debt-balance" }, d.balance === null || d.balance === "" || d.balance === undefined ? "Unknown balance" : money(d.balance)), el("p", { class: "debt-meta" }, `Reported as of ${prettyDate(d.as_of)}`), el("p", { class: "debt-meta" }, `Minimum payment: ${d.minimum_payment == null || d.minimum_payment === "" ? "Not provided" : money(d.minimum_payment)} · Due: ${prettyDate(d.due_date)}`), el("p", { class: "debt-meta break-word" }, `Source: ${d.source || "Not provided"}`)))) : empty("Keep obligations in view", "Record a debt with the balance and date you know. Unknown information stays unknown.", "wallet", button("Add a debt", () => debtDialog(), { variant: "secondary", small: true }), true);
    root.append(el("div", { class: "page-grid" }, card("Spending plans", "A plan is an intention, not a prediction.", budgetBody, button("Add plan", () => budgetDialog(), { variant: "tertiary", small: true, glyph: "plus" }), "Plans use matching expense categories and each plan’s own date range."), card("Debts", "Balances supplied by you, with an as-of date.", debtBody, button("Add debt", () => debtDialog(), { variant: "tertiary", small: true, glyph: "plus" }), "Balances do not automatically change when you record a payment.")), el("div", { class: "section-gap" }, note("This workspace does not calculate net worth from incomplete records. Account balances and debt details must come from information you provide.")));
    return root;
  }
  function budgetDialog() {
    const form = el("form", {}, el("div", { class: "form-grid" }, field("Category", "category", "text", "", { required: true, placeholder: "Match an expense category exactly", full: true }), field("Planned amount (USD)", "amount", "number", "", { required: true, min: "0", step: "0.01", full: true }), field("Starts", "start_date", "date", setup().start_date, { required: true }), field("Ends", "end_date", "date", setup().end_date, { required: true })), el("div", { class: "form-actions" }, submitButton("Review this plan")));
    submitForm(form, async values => { if (values.end_date < values.start_date) throw new Error("The end date must be on or after the start date."); await propose("budget", values); closeDialog(); }); openDialog("Create a spending plan", "Compare a category’s approved expenses with your chosen amount.", form);
  }
  function debtDialog() {
    const form = el("form", {}, el("div", { class: "form-grid" }, field("Debt name", "label", "text", "", { required: true, full: true, placeholder: "e.g. Student loan" }), field("Reported balance (USD)", "balance", "number", "", { min: "0", step: "0.01", help: "Leave blank if unknown." }), field("Balance as of", "as_of", "date", "", { help: "Required when you provide a balance. Leave blank if unknown." }), field("Minimum payment (USD)", "minimum_payment", "number", "", { min: "0", step: "0.01", help: "Leave blank if unknown." }), field("Next due date", "due_date", "date", ""), field("Source", "source", "text", "", { full: true, required: true, placeholder: "e.g. October statement or my estimate" })), note("Keep estimates clearly identified in the source. A saved debt record does not create a transaction or an automatic payment."), el("div", { class: "form-actions" }, submitButton("Review this debt")));
    submitForm(form, async values => { ["balance", "minimum_payment", "as_of", "due_date"].forEach(k => { if (values[k] === "") values[k] = null; }); await propose("debt", values); closeDialog(); }); openDialog("Add a debt", "Record what you know and leave the rest open.", form);
  }
  function renderAdd() {
    const root = el("div", {}, heading("Start with what you have", "A little information goes a long way.", "Bring an entry, a local file, or a few notes. You stay in charge of what gets saved."));
    const tabs = [["manual", "Enter a transaction"], ["files", "Upload a file"], ["notes", "Notes & local AI"]];
    root.append(el("div", { class: "tabs", role: "tablist", "aria-label": "Ways to add information" }, tabs.map(([id, label], i) => el("button", { class: `tab${app.addTab === id ? " active" : ""}`, type: "button", role: "tab", id: `tab-${id}`, "aria-controls": "add-panel", "aria-selected": app.addTab === id ? "true" : "false", tabindex: app.addTab === id ? "0" : "-1", onclick: () => { if (pendingAction()) return; app.addTab = id; renderPage(); if (id === "notes") loadModelStatus(); }, onkeydown: e => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) { e.preventDefault(); if (pendingAction()) return; const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; app.addTab = tabs[next][0]; renderPage(); $(`#tab-${app.addTab}`).focus(); if (app.addTab === "notes") loadModelStatus(); } } }, label))));
    const content = app.addTab === "manual" ? el("div", { class: "page-grid" }, card("Add a transaction", "The essentials, in your own words.", el("div", { class: "card-body" }, transactionForm(app.drafts.transaction))), el("div", { class: "stack" }, card("A useful distinction", null, el("div", { class: "card-body" }, el("ul", { class: "info-list" }, [["up", "Income & expenses", "Use these for earnings and spending."], ["arrows", "Transfers & loans", "Moving money between your own accounts is not income. Borrowing is recorded separately."], ["help", "Not sure yet?", "Choose Unclassified. It stays visible for a later decision."]].map(([glyph, title, copy]) => el("li", {}, icon(glyph), el("div", {}, el("strong", {}, title), el("p", {}, copy))))))), el("div", { class: "quiet-card" }, el("h3", {}, "You have the final say."), el("p", {}, "Every new entry or edit becomes a proposal. Your saved overview changes only when you approve it.")))) : app.addTab === "files" ? uploadView() : notesView();
    root.append(el("div", { id: "add-panel", role: "tabpanel", "aria-labelledby": `tab-${app.addTab}` }, content)); return root;
  }
  function uploadView() {
    return el("div", { class: "page-grid" }, card("Preview a local file", "Choose exactly what you want this workspace to read.", el("div", { class: "card-body" }, uploadControl(), app.previews.map(p => previewCard(p)))), el("div", { class: "stack" }, card("One step at a time", null, el("div", { class: "card-body" }, el("ul", { class: "info-list" }, [["file", "Preview", "Selecting a file reads that selected file into the local app for a temporary preview."], ["folder", "Keep a copy, if you choose", "Use “Keep local copy” to explicitly add the original file to your local library."], ["review", "Review extracted entries", "Supported rows become proposals. Check dates, amounts, and classifications before approval."]].map(([glyph, title, copy]) => el("li", {}, icon(glyph), el("div", {}, el("strong", {}, title), el("p", {}, copy))))))), el("div", { class: "quiet-card" }, el("h3", {}, "Scans and PDFs need care."), el("p", {}, "Unsupported files are labelled clearly. For scanned documents, use your own local OCR tool and paste the text or enter the information manually. No remote OCR is used."))));
  }
  function uploadControl() {
    const input = el("input", { type: "file", "aria-label": "Choose a local file to preview", accept: ".csv,.tsv,.xlsx,.txt,.zip,.pdf" });
    const status = el("div", { role: "status", "aria-live": "polite" });
    input.addEventListener("change", async () => {
      const file = input.files?.[0]; if (!file) return;
      if (file.size > 10000000) { toast("This file exceeds the 10 MB preview limit. Choose a smaller file.", true); input.value = ""; return; }
      input.disabled = true; status.replaceChildren(el("div", { class: "pending-status" }, el("span", { class: "spinner" }), "Reading only your selected file…"));
      try { const result = await api("/api/upload", { name: file.name, base64: await fileBase64(file) }, 90000); app.previews.unshift(result); toast("File preview ready. No file copy or transactions have been saved."); renderPage(); }
      catch (error) { status.replaceChildren(notice("The file could not be previewed", error.message, null, "error")); }
      finally { input.disabled = false; input.value = ""; }
    });
    return el("div", {}, el("div", { class: "file-drop" }, el("div", { class: "empty-icon" }, icon("upload")), el("h3", {}, "Bring a file from your computer"), el("p", {}, "CSV, TSV, XLSX, text, or ZIP · up to 10 MB"), el("p", {}, "PDF support is limited; the preview will explain what is available."), input), status);
  }
  function fileBase64(file) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = () => reject(new Error("The browser could not read that file.")); reader.readAsDataURL(file); }); }
  function previewCard(preview) {
    const status = preview.status || "preview"; const entries = preview.entries || preview.members || []; const rows = preview.rows || [];
    const box = el("section", { class: "file-preview" }, el("div", { class: "file-preview-header" }, el("div", {}, el("h3", {}, preview.name || "File preview"), el("p", { class: "subtle" }, preview.saved ? "Local copy saved to your library" : "Temporary preview · not saved")), badge(humanize(status), ["unsupported", "rejected"].includes(status) ? "warning" : "neutral")));
    if (preview.warnings?.length) box.append(el("ul", { class: "warning-list" }, preview.warnings.map(w => el("li", {}, typeof w === "string" ? w : JSON.stringify(w)))));
    if (status === "unsupported" || status === "rejected") box.append(note("This file cannot be converted into entries here. You can enter its information manually, or use a local tool to extract readable text."));
    if (entries.length) box.append(el("p", { class: "muted-line" }, "Choose an individual member to preview. Opening a ZIP does not import every file."), el("ul", { class: "file-list" }, entries.map(entry => el("li", {}, icon("file"), el("div", { class: "break-word", style: "flex:1" }, el("strong", {}, entry.name), el("p", {}, `${entry.size == null ? "Size unknown" : `${(entry.size / 1024).toFixed(1)} KB`} · ${humanize(entry.status || "available")}`)), button("Preview", async () => { const member = await api("/api/zip-member", { id: preview.id, member: entry.name }); app.previews.unshift(member); renderPage(); }, { variant: "secondary", small: true })))));
    if (rows.length) {
      box.append(el("p", { class: "preview-section-title" }, `${rows.length} ${rows.length === 1 ? "row" : "rows"} detected`));
      const cols = [...new Set(rows.slice(0, 8).flatMap(r => Object.keys(r)))].slice(0, 8);
      box.append(el("div", { class: "table-scroll", tabindex: "0", "aria-label": "File rows preview", role: "region" }, el("table", { class: "data-table compact-table" }, el("thead", {}, el("tr", {}, cols.map(key => el("th", { scope: "col" }, humanize(key))))), el("tbody", {}, rows.slice(0, 8).map(row => el("tr", {}, cols.map(key => el("td", {}, typeof row[key] === "object" ? JSON.stringify(row[key]) : row[key]))))))));
      if (rows.length > 8) box.append(el("p", { class: "subtle mt-12" }, `Showing the first 8 of ${rows.length} rows. Review the full proposal before approval.`));
    }
    if (preview.text) box.append(el("details", { class: "mt-12" }, el("summary", { class: "muted-line" }, "Read extracted text"), el("pre", {}, String(preview.text).slice(0, 50000)), String(preview.text).length > 50000 ? el("p", { class: "subtle" }, "Text display limited to 50,000 characters.") : null));
    const actions = el("div", { class: "button-row mt-20" });
    if (!preview.saved && status !== "rejected") actions.append(button("Keep local copy", async () => { await api("/api/import", { id: preview.id }); preview.saved = true; await refresh(); toast("The selected original file was copied to your local library."); }, { variant: "secondary", small: true, glyph: "folder" }));
    if (rows.length && status !== "rejected") actions.append(button("Propose these entries", async () => { await api("/api/import-propose", { id: preview.id }); await refresh({ rerender: false }); navigate("review"); toast("Extracted entries are ready for your review."); }, { small: true, glyph: "review" }));
    actions.append(button("Dismiss preview", () => { app.previews = app.previews.filter(p => p !== preview); renderPage(); }, { variant: "tertiary", small: true })); box.append(actions); return box;
  }
  async function loadModelStatus() {
    try { app.modelStatus = await api("/api/model/status"); } catch (error) { app.modelStatus = { running: false, message: error.message }; }
    const target = $("#model-status"); if (target) { target.textContent = modelStatusText(); target.classList.toggle("running", !!app.modelStatus?.running); }
  }
  function modelStatusText() { if (!app.modelStatus) return "Local AI is optional. No model starts automatically."; return app.modelStatus.message || (app.modelStatus.running ? "Your dedicated local model session is running." : "Your dedicated local model session is not running."); }
  function notesView() {
    const notes = field("Your notes", "notes", "textarea", app.drafts.notes, { rows: 10, placeholder: "For example: I paid $48.20 for groceries on October 12 from checking. Ask me about anything that is missing.", help: "This draft stays only in this open tab. It is not sent or saved automatically.", oninput: e => { app.drafts.notes = e.target.value; }, full: true });
    const executable = field("Ollama executable path (optional)", "executable", "text", app.drafts.executable, { placeholder: "Full path to ollama.exe, if needed", help: "Leave blank to use the locally discovered Ollama installation.", oninput: e => { app.drafts.executable = e.target.value; } });
    const model = field("Installed model name", "model", "text", app.drafts.model, { placeholder: "Enter the exact name of your installed model", help: "Use a model already installed on this computer. The app does not download one.", oninput: e => { app.drafts.model = e.target.value; } });
    const docChoices = documents().length ? el("div", { class: "check-panel mb-16" }, el("div", { class: "field-label" }, "Include selected library files"), el("p", { class: "field-help mt-12" }, "Only checked files will be supplied to the local model."), el("div", { class: "source-list mt-12" }, documents().map(d => el("label", { class: "check-label" }, el("input", { type: "checkbox", checked: app.drafts.documentIds.has(d.id), onchange: e => { if (e.target.checked) app.drafts.documentIds.add(d.id); else app.drafts.documentIds.delete(d.id); } }), el("span", { class: "break-word" }, d.name))))) : null;
    const analyzeButton = button(app.analysisBusy ? "Working locally…" : "Prepare a proposal with local AI", async b => {
      if (!app.drafts.notes.trim() && !app.drafts.documentIds.size) throw new Error("Add notes or explicitly select a library file first.");
      if (!app.drafts.model.trim()) throw new Error("Enter the exact name of an installed local model first.");
      app.analysisBusy = true; app.analysis = null;
      const status = $("#analysis-status"); status.replaceChildren(el("div", { class: "pending-status" }, el("span", { class: "spinner" }), "Preparing a proposal locally. This may take a few minutes. No automatic retries."));
      b.setAttribute("aria-busy", "true");
      try { app.analysis = await api("/api/analyze", { text: app.drafts.notes, document_ids: [...app.drafts.documentIds], model: app.drafts.model.trim() }, 180000); await refresh({ rerender: false }); renderNavigation(); if (app.page === "add" && app.addTab === "notes") renderPage(); toast(app.analysis.proposal ? "The local model prepared a proposal. Review every detail before approval." : "The local model response is ready to inspect."); }
      finally { app.analysisBusy = false; b.removeAttribute("aria-busy"); if (app.page === "add" && app.addTab === "notes") renderPage(); }
    }, { glyph: "spark", disabled: app.analysisBusy });
    const left = card("Turn your notes into a starting point", "Optional help from a model running on this computer.", el("div", { class: "card-body" }, notes, docChoices, el("div", { class: "button-row" }, analyzeButton, button("Clear draft", () => { if (!app.drafts.notes || confirm("Clear these unsaved notes?")) { app.drafts.notes = ""; app.analysis = null; renderPage(); } }, { variant: "tertiary", small: true })), el("div", { id: "analysis-status", role: "status", "aria-live": "polite" }, app.analysisBusy ? el("div", { class: "pending-status" }, el("span", { class: "spinner" }), "The local model is still working. Nothing will be approved automatically.") : null), analysisResult()));
    const right = el("div", { class: "stack" }, card("Your local model session", "Kept separate from other Ollama sessions.", el("div", { class: "card-body" }, model, executable, el("div", { id: "model-status", class: `model-status${app.modelStatus?.running ? " running" : ""}`, role: "status" }, modelStatusText()), el("div", { class: "button-row" }, button("Start local session", async () => { if (!app.drafts.model.trim()) throw new Error("Enter the name of an installed model first."); if (!confirm("Start a dedicated Ollama session for this workspace? It runs locally and may use memory and processing power. Your notes will not be sent until you choose the proposal button.")) return; const result = await api("/api/model/start", { executable: app.drafts.executable.trim(), model: app.drafts.model.trim() }, 90000); app.modelStatus = result; await loadModelStatus(); toast("Local session request completed. Check the session status before analyzing."); }, { variant: "secondary", small: true }), button("Check status", () => loadModelStatus(), { variant: "tertiary", small: true })), el("p", { class: "field-help mt-12" }, "If Ollama is unavailable, manual entry and file review still work."))), el("div", { class: "quiet-card" }, el("h3", {}, "Helpful, and still fallible."), el("p", {}, "The model can misunderstand dates, amounts, and categories. Notes and file text can also be incomplete or misleading. Check the original sources. Missing details remain questions; approval always belongs to you."), el("p", {}, "This app uses its local service. Your operating system, browser, extensions, and other programs have their own permissions.")));
    return el("div", { class: "page-grid" }, left, right);
  }
  function analysisResult() {
    const a = app.analysis; if (!a) return null;
    const result = el("div", { class: "mt-20" });
    if (a.warnings?.length) result.append(el("div", { class: "review-warnings" }, el("strong", {}, "Please check"), el("ul", {}, a.warnings.map(w => el("li", {}, String(w))))));
    if (a.questions?.length) result.append(el("div", { class: "review-warnings" }, el("strong", {}, "Information to clarify"), el("ul", {}, a.questions.map(q => el("li", {}, String(q))))), el("p", { class: "muted-line" }, "Add the answers to your notes and prepare another proposal when ready. Existing drafts are not overwritten."));
    if (a.proposal) result.append(notice("A proposal is ready", "Review its source, amounts, and classifications before you approve anything.", button("Open review", () => navigate("review"), { variant: "secondary", small: true }), "success"));
    if (a.text || a.message) result.append(el("p", { class: "muted-line" }, a.text || a.message));
    return result;
  }
  function renderReview() {
    const pending = proposals(); const root = el("div", {}, heading("Your decision, every time", "Make sure it feels right.", "These are proposals. Your saved records stay as they are until you approve a change."));
    if (!pending.length) return el("div", {}, root, card(null, null, empty("You’re all caught up", "New entries, edits, extracted rows, and local AI suggestions will wait here for your approval.", "check", button("Add information", () => navigate("add"), { variant: "secondary" }))));
    root.append(el("div", { class: "review-list" }, pending.map(reviewCard))); return root;
  }
  const kindTitles = { transaction: "Transaction", transactions: "Imported transactions", setup: "Workspace setup", budget: "Spending plan", debt: "Debt record", delete_transaction: "Delete a transaction", demo: "Sample records", restore: "Restore a backup" };
  async function reviewAction(action) {
    if (app.reviewBusy) return;
    app.reviewBusy = true;
    syncPendingUI();
    $("#main").querySelectorAll(".review-card button, .review-card input").forEach(control => { control.disabled = true; });
    try { await action(); } finally { app.reviewBusy = false; renderPage(); }
  }
  function reviewCard(proposal) {
    const data = proposal.data || {}; const kind = proposal.kind || "change"; const isDelete = kind === "delete_transaction";
    const root = el("section", { class: "card review-card" }, el("div", { class: "review-heading" }, el("div", { class: "review-heading-left" }, el("span", { class: "empty-icon", style: "width:38px;height:38px;border-radius:10px;margin:0" }, icon(isDelete ? "stop" : "review")), el("div", {}, el("h2", {}, kindTitles[kind] || humanize(kind)), el("p", {}, `Proposed against revision ${proposal.base_revision ?? "unknown"}${proposal.created_at ? ` · ${prettyDate(proposal.created_at)}` : ""}`))), badge(isDelete ? "Deletion" : "Awaiting approval", isDelete ? "danger" : "warning")));
    if (kind === "transaction" && data.id) { const previous = transactions().find(t => t.id === data.id); if (previous) root.append(el("p", { class: "muted-line" }, `Replaces “${previous.description}” · ${money(previous.amount)} · ${prettyDate(previous.date)}. The values below are the proposed replacement.`)); }
    if (isDelete) { const previous = transactions().find(t => t.id === data.id); root.append(note(previous ? `This removes “${previous.description}”, ${money(previous.amount)}, dated ${prettyDate(previous.date)} from your saved transactions.` : `This removes transaction ${data.id}.`, "stop")); }
    const rows = Array.isArray(data) ? data : data.transactions || data.rows || data.entries;
    if (Array.isArray(rows)) {
      root.append(el("p", { class: "muted-line" }, `${rows.length} proposed ${rows.length === 1 ? "entry" : "entries"}. Inspect every row before approval.`), transactionTable(rows, false));
    } else if (!isDelete) {
      const entries = Object.entries(data).filter(([key]) => !["id", "privacy_acknowledged"].includes(key));
      root.append(el("div", { class: "review-details" }, entries.map(([key, value]) => el("div", {}, el("div", { class: "detail-label" }, humanize(key)), el("div", { class: "detail-value" }, value === null || value === "" || value === undefined ? "Not provided" : ["amount", "balance", "minimum_payment"].includes(key) ? money(value) : typeof value === "object" ? JSON.stringify(value) : String(value))))));
    }
    const warnings = [...(proposal.warnings || []), ...(proposal.questions || []).map(q => `Question: ${typeof q === "string" ? q : JSON.stringify(q)}`)];
    if (warnings.length) root.append(el("div", { class: "review-warnings" }, el("strong", {}, "Items that need your attention"), el("ul", {}, warnings.map(w => el("li", {}, typeof w === "string" ? w : JSON.stringify(w))))));
    if (kind === "setup" && data.privacy_acknowledged) root.append(note("You acknowledged the local privacy boundaries. Optional AI remains off until you choose to start and use a local session.", "shield"));
    const stale = proposal.base_revision !== undefined && number(proposal.base_revision) !== number(state().revision ?? overview().revision);
    const invalid = proposal.valid === false || (proposal.questions || []).length > 0;
    const duplicateCount = number(proposal.duplicate_count);
    let warningsChecked = warnings.length === 0;
    let duplicatesChecked = duplicateCount === 0;
    if (invalid) root.append(notice("A correction is needed before approval", "Use the correction form to resolve the questions and create a fresh proposal. Your current records are unchanged.", null, "error"));
    if (stale) root.append(notice("Saved records have changed", "This proposal is based on an older revision. Reject it and prepare a fresh proposal against your current records.", null, "error"));
    const approve = button(isDelete ? "Approve deletion" : "Approve & save", () => reviewAction(async () => {
      if (isDelete && !confirm("Approve this deletion? This removes the transaction from the current saved records.")) return;
      try { await api("/api/approve", { id: proposal.id, revision: proposal.base_revision, allow_duplicates: duplicateCount > 0 && duplicatesChecked }); await refresh(); toast(isDelete ? "The approved transaction deletion was saved." : "Approved and saved. Your overview has been updated."); }
      catch (error) {
        let refreshed = false; try { await refresh(); refreshed = true; } catch (_) { /* Keep the reviewed values visible. */ }
        if (!error.status) throw new Error(`${error.message} Approval was not retried. ${refreshed ? (proposals().some(p => p.id === proposal.id) ? "The proposal is still pending in the refreshed records; check it before trying again." : "This proposal is no longer pending. Inspect the refreshed saved records before creating another change.") : "The saved result could not be confirmed. Reconnect and refresh saved records before trying again."}`);
        throw error;
      }
    }), { glyph: "check", variant: isDelete ? "danger" : "", disabled: stale || invalid || !warningsChecked || !duplicatesChecked });
    const syncApproval = () => { approve.disabled = app.reviewBusy || stale || invalid || !warningsChecked || !duplicatesChecked; };
    const check = el("div", { class: "checking-list" }, warnings.length ? el("label", { class: "check-label" }, el("input", { type: "checkbox", onchange: e => { warningsChecked = e.target.checked; syncApproval(); } }), el("span", {}, "I have reviewed the warnings.")) : el("span", { class: "subtle" }, "Your approval updates the saved records."));
    if (duplicateCount) check.append(el("label", { class: "check-label" }, el("input", { type: "checkbox", onchange: e => { duplicatesChecked = e.target.checked; syncApproval(); } }), el("span", {}, `I checked these ${duplicateCount} possible ${duplicateCount === 1 ? "duplicate" : "duplicates"} and want to keep them.`)));
    root.append(el("div", { class: "review-actions" }, check, el("div", { class: "button-row" }, !isDelete ? button("Correct proposal", () => correctionDialog(proposal), { variant: "secondary" }) : null, button("Reject proposal", () => reviewAction(async () => { if (!confirm("Discard this proposal? Existing saved records will stay unchanged.")) return; await api("/api/reject", { id: proposal.id }); await refresh(); toast("Proposal discarded."); }), { variant: "secondary" }), approve)));
    return root;
  }
  function correctionDialog(proposal) {
    const original = proposal.data;
    if (!["transaction", "transactions"].includes(proposal.kind)) {
      const form = el("form");
      const values = original && typeof original === "object" && !Array.isArray(original) ? original : {};
      const grid = el("div", { class: "form-grid" });
      Object.entries(values).filter(([key]) => key !== "id").forEach(([key, value]) => {
        if (key === "privacy_acknowledged") { grid.append(el("label", { class: "check-label full-width" }, el("input", { type: "checkbox", name: key, value: "true", checked: value === true }), el("span", {}, "I understand the local privacy boundaries described in Settings & help."))); return; }
        const type = ["start_date", "end_date", "as_of", "due_date"].includes(key) ? "date" : ["amount", "balance", "minimum_payment"].includes(key) ? "number" : key === "goals" ? "textarea" : "text";
        grid.append(field(humanize(key), key, type, value ?? "", { full: ["goals", "source", "label", "category"].includes(key), ...(type === "number" ? { step: "0.01", min: "0" } : {}) }));
      });
      form.append(grid, note("Correct the values you can verify. A new proposal will be checked against your current records; it will still need your approval."), el("div", { class: "form-actions" }, submitButton("Create corrected proposal")));
      submitForm(form, async values => { if (proposal.kind === "setup" && "privacy_acknowledged" in original) values.privacy_acknowledged = $("input[name=privacy_acknowledged]", form).checked; if (["setup", "debt", "budget"].includes(proposal.kind)) Object.keys(values).forEach(k => { if (!values[k] && ["balance", "minimum_payment", "amount", "as_of", "due_date", "start_date", "end_date"].includes(k)) values[k] = null; }); await replaceProposal(proposal, values); closeDialog(); });
      openDialog("Correct this proposal", "Your saved records stay unchanged until you approve the replacement.", form); return;
    }
    let rows = (proposal.kind === "transactions" ? original : [original]).map(r => ({ ...r }));
    let index = 0;
    const form = el("form"); const picker = el("select", { "aria-label": "Transaction row to correct" }); const rowArea = el("div"); const rowSummary = el("p", { class: "muted-line mb-16" });
    const pull = (submitted) => { const current = submitted ? { ...submitted } : Object.fromEntries(new FormData(form).entries()); if (!current.category?.trim()) current.category = "Uncategorized"; if (rows[index]?.id && proposal.kind === "transaction") current.id = rows[index].id; rows[index] = current; };
    const draw = () => {
      rowSummary.textContent = `Editing row ${index + 1} of ${rows.length}. Switch rows to check each entry; changes remain in this form until you create a proposal.`;
      picker.replaceChildren(...rows.map((r, i) => el("option", { value: i }, `Row ${i + 1} · ${r.description || "No description"}`))); picker.value = String(index);
      const row = rows[index];
      rowArea.replaceChildren(el("div", { class: "form-grid" }, field("Date", "date", "date", row.date || "", { required: true, help: row.date ? `Source value: ${row.date}` : "Supply the actual date; do not guess." }), field("Amount (USD, signed)", "amount", "number", row.amount ?? "", { required: true, step: "0.01", help: `Source value: ${row.amount ?? "Not provided"}. Negative means money out.` }), field("Description", "description", "text", row.description || "", { required: true, full: true }), field("Account", "account", "text", row.account || "", { required: true }), field("Type", "classification", "select", row.classification || "unclassified", { choices: ["unclassified", "income", "expense", "transfer", "loan", "refund"] }), field("Category", "category", "text", row.category || "Uncategorized"), field("Source", "source", "text", row.source || "")));
    };
    picker.addEventListener("change", () => { const next = number(picker.value); pull(); index = next; draw(); });
    form.append(el("div", { class: "field" }, el("label", {}, "Choose a row to inspect"), picker), rowSummary, rowArea);
    if (proposal.kind === "transactions") form.append(el("div", { class: "button-row mb-16" }, button("Previous row", () => { pull(); index = Math.max(0, index - 1); draw(); }, { variant: "secondary", small: true }), button("Next row", () => { pull(); index = Math.min(rows.length - 1, index + 1); draw(); }, { variant: "secondary", small: true }), button("Remove this row", () => { if (rows.length === 1) { toast("A proposal needs at least one row. Reject the proposal instead if you do not want this entry.", true); return; } if (!confirm(`Remove row ${index + 1} from this corrected proposal?`)) return; rows.splice(index, 1); index = Math.min(index, rows.length - 1); $("#app-dialog").dataset.dirty = "1"; draw(); }, { variant: "danger", small: true })));
    form.append(note("This creates a fresh proposal and discards the one it replaces. Resolve missing details using your own information. The replacement will still need approval."), el("div", { class: "form-actions" }, submitButton("Create corrected proposal")));
    submitForm(form, async values => { pull(values); await replaceProposal(proposal, proposal.kind === "transaction" ? rows[0] : rows); closeDialog(); }); draw();
    openDialog("Correct proposed transactions", "Edit dates, amounts, types, and sources without changing saved records.", form);
  }
  async function replaceProposal(proposal, data) {
    await api("/api/propose", { kind: proposal.kind, data });
    try { await api("/api/reject", { id: proposal.id }); } catch (_) { toast("The corrected proposal was created, but the earlier proposal could not be discarded. Review both carefully.", true); }
    await refresh({ rerender: false }); navigate("review", { afterSubmit: true }); toast("Corrected proposal created. Check its validation and approve it when ready.");
  }
  function renderFiles() {
    const library = documents();
    const root = el("div", {}, heading("Yours to keep", "Files, records, and a way back.", "Manage the originals you chose to keep and export an independent copy of your records.", button("Preview a file", () => navigate("add", { tab: "files" }), { glyph: "upload" })));
    const exportCards = [["xlsx", "Excel workbook", "Transactions and summaries in a spreadsheet you can use independently."], ["csv", "Transactions CSV", "A portable transaction table for another spreadsheet or tool."], ["html", "Readable report", "A local HTML report you can open in your browser or print."], ["json", "Data JSON", "Structured records for your own tools and further analysis."], ["backup", "Complete backup", "A portable archive for recovery. Keep a copy somewhere you trust."]];
    root.append(el("div", { class: "page-grid" }, card("Your local file library", `${library.length} ${library.length === 1 ? "file" : "files"} explicitly kept in this workspace`, library.length ? el("div", { class: "card-body" }, el("ul", { class: "file-list" }, library.map(d => el("li", {}, el("span", { class: "entity-icon" }, icon("file")), el("div", { style: "flex:1;min-width:0" }, el("strong", {}, d.name), el("p", {}, `${humanize(d.status || "saved")} · Version ${d.version || 1} · ${d.imported_at || d.created_at ? prettyDate(d.imported_at || d.created_at) : "Local copy"}`)), button("Preview", async () => { const result = await api("/api/document-preview", { id: d.id }); app.previews.unshift({ ...result, saved: true }); navigate("add", { tab: "files" }); }, { variant: "secondary", small: true }))))) : empty("Keep only what you choose", "Previewing a file does not add it here. Select “Keep local copy” when you want to retain the original.", "folder", button("Preview a file", () => navigate("add", { tab: "files" }), { variant: "secondary", small: true }), true), null, "Files are not automatically sent to a model. Select them explicitly in Notes & local AI."), card("Take your records with you", "Exports reflect approved, saved information.", el("div", { class: "card-body" }, el("div", { class: "export-grid" }, exportCards.map(([format, title, copy]) => {
      const b = el("button", { type: "button", class: "export-card" }, icon(format === "backup" ? "shield" : "download"), el("span", {}, el("strong", {}, title), el("small", {}, copy)));
      b.addEventListener("click", async () => { b.disabled = true; try { await downloadExport(format); } catch (error) { toast(error.message, true); } finally { b.disabled = false; } }); return b;
    })), el("p", { class: "restore-help" }, "For backup recovery, close the app and follow the included recovery instructions. Preserve your current data folder before replacing any files.")))));
    root.append(el("div", { class: "section-gap" }, note("Exports may contain your financial information. They use your browser’s download location; storage permissions and protection are managed by your operating system."))); return root;
  }
  async function downloadExport(format) {
    const result = await api("/api/export", { format }, 90000); const url = new URL(result.url, location.origin);
    if (url.origin !== location.origin) throw new Error("The service returned an export outside this local workspace.");
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error("The export could not be downloaded. Please try again.");
    const blob = await response.blob(); const objectUrl = URL.createObjectURL(blob); const a = el("a", { href: objectUrl, download: result.filename || `private-accounting.${format}`, style: "display:none" }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(objectUrl), 30000); toast("Export prepared and sent to your browser’s downloads.");
  }
  function setupForm(welcome = false) {
    const s = { ...setup(), ...app.drafts.setup }; const form = el("form");
    form.addEventListener("input", e => { if (e.target.name) app.drafts.setup[e.target.name] = e.target.type === "checkbox" ? e.target.checked : e.target.value; });
    form.append(el("div", { class: "form-grid" }, field("What would you like to understand?", "goals", "textarea", Array.isArray(s.goals) ? s.goals.join("\n") : s.goals, { rows: 2, full: true, placeholder: "e.g. Understand my monthly spending and plan for a move.", help: "Optional. A note to yourself, not a financial recommendation." }), field("Overview starts (optional)", "start_date", "date", s.start_date, { help: "Blank includes all earlier dates." }), field("Overview ends (optional)", "end_date", "date", s.end_date, { help: "Blank includes all later dates." }), field("Currency", "currency", "select", "USD", { choices: [{ value: "USD", label: "USD — US dollar" }], full: true, help: "Amounts use one currency. No currency conversion is performed." })));
    const consent = el("input", { type: "checkbox", name: "privacy_acknowledged", required: true, checked: !!s.privacy_acknowledged, value: "true" });
    form.append(el("div", { class: "check-panel" }, el("label", { class: "check-label" }, consent, el("span", {}, "I understand that selected information is processed by this local app. Optional AI runs only after I configure and request it. Browser, operating-system, and other software permissions are separate."))), el("div", { class: "form-actions" }, welcome ? button("Explore first", () => closeDialog(), { variant: "tertiary" }) : el("span", { class: "subtle" }, "Setup changes also need your approval."), submitButton(welcome ? "Review my setup" : "Review setup changes")));
    submitForm(form, async values => { if (values.start_date && values.end_date && values.end_date < values.start_date) throw new Error("The end date must be on or after the start date."); values.start_date = values.start_date || null; values.end_date = values.end_date || null; values.privacy_acknowledged = consent.checked; await propose("setup", values); app.drafts.setup = {}; if (welcome) closeDialog(); }); return form;
  }
  function welcomeDialog() {
    app.welcomed = true;
    openDialog("A quieter place for your finances.", "Welcome to Private Accounting. A few details will make this workspace yours.", el("div", {}, el("div", { class: "welcome-points" }, note("Files are read only when you select them. Keeping an original copy is a separate choice.", "folder"), note("Every change is a proposal until you review and approve it.", "review"), note("Local AI is optional and off until you explicitly start a session.", "shield")), setupForm(true)), { dirtyGuard: false });
  }
  function renderSettings() {
    const root = el("div", {}, heading("Built around your choices", "Your workspace, your way.", "Set your reporting period, understand the boundaries, and keep your work portable."));
    const help = [["What do the dashboard amounts mean?", "Income and expenses include only approved transactions with those classifications, within the overview’s selected dates. Income minus expenses excludes transfers, loans, refunds, and unclassified entries. Net cash movement adds all signed transaction amounts; it is not a bank balance."], ["Why are account balances and net worth unknown?", "A list of transactions is not enough to establish account balances. Opening balances, complete histories, and asset and debt information may be missing. The app does not invent them."], ["What happens to pending work when I close this?", "Unsaved notes and form drafts live in this tab’s memory. Pending proposals and temporary file previews may be lost when the local service ends. Approve the records you want to keep, and download a backup of saved data before moving or replacing the workspace."], ["How should I handle a possible duplicate?", "Check the source and transaction details. Duplicate warnings are a reason to pause. Compare the proposal with existing records. Remove accidental repeats using the correction form. If repeated entries are intentional, explicitly acknowledge the duplicate warning before approving."], ["What does local-only cover?", "The app uses its local service and has no remote model or document-processing integration. Optional AI uses a dedicated local Ollama session. Your browser, extensions, operating system, backups, synchronization tools, and other programs have separate access and settings."], ["How do I move or recover my records?", "Export a complete backup. Follow the recovery instructions included with the application, using a fresh location and retaining the current data folder. A backup only contains saved information; it does not preserve an unsent browser draft."]];
    const storage = app.snapshot.data_dir || app.snapshot.settings?.data_dir || "The application’s local data folder";
    root.append(el("div", { class: "page-grid" }, card("Workspace setup", "Your goals and the dates used on your overview.", el("div", { class: "card-body" }, setupForm())), el("div", { class: "stack" }, card("Stored on this computer", null, el("div", { class: "card-body" }, note("Your files and approved records stay in the configured local workspace.", "shield"), el("div", { class: "path-display" }, storage), el("p", { class: "field-help" }, `Saved revision ${state().revision ?? overview().revision ?? 0}${app.snapshot.version ? ` · App ${app.snapshot.version}` : ""}`), button("Files & exports", () => navigate("files"), { variant: "tertiary", small: true, glyph: "arrow" }), el("div", { class: "setting-section" }, el("h3", {}, "Optional local AI"), el("p", { class: "muted-line" }, "Configure a dedicated local model session and choose exactly which notes or files to analyze."), el("div", { class: "mt-12" }, button("Set up local AI", () => navigate("add", { tab: "notes" }), { variant: "secondary", small: true, glyph: "spark" }))), el("div", { class: "setting-section" }, el("h3", {}, "Explore with sample records"), el("p", { class: "muted-line" }, "Create a clearly labelled fictional dataset as a proposal. It is only added if you approve it."), el("div", { class: "mt-12" }, button("Prepare sample data", async () => { if (!confirm("Prepare fictional sample transactions for this workspace? They will wait in Review and only be saved if you approve them. Use an empty workspace to keep sample and personal records separate.")) return; await api("/api/demo", {}); await refresh({ rerender: false }); navigate("review"); toast("Fictional sample data is ready for review."); }, { variant: "secondary", small: true }))), el("div", { class: "setting-section" }, el("h3", {}, "Close the local workspace"), el("p", { class: "muted-line" }, "Ends this app’s local service. Save or export anything you want to keep first."), el("div", { class: "mt-12" }, button("Shut down workspace", async () => { if (!confirm("Shut down this local workspace now? Unsaved notes, pending proposals, and temporary file previews may be lost. Approved records remain in the local data folder.")) return; await api("/api/shutdown", { confirm: true }); app.connected = false; $("#connection-status").textContent = "Workspace closed"; $("#main").replaceChildren(el("div", { class: "error-screen" }, el("div", { class: "empty-icon" }, icon("check")), el("h1", {}, "Your workspace is closed."), el("p", {}, "Approved records remain in your local data folder. You can close this browser tab. Use the launcher when you are ready to return."))); }, { variant: "danger", small: true, glyph: "stop" })))))), card("A little guidance", null, el("div", { class: "card-body" }, help.map(([question, answer]) => el("details", { class: "faq" }, el("summary", {}, question), el("p", {}, answer)))))));
    return root;
  }
  function syncSidebar() {
    const mobile = window.innerWidth <= 680; const open = $("#sidebar").classList.contains("open");
    $("#sidebar").inert = mobile && !open;
    $("#menu-toggle").setAttribute("aria-expanded", String(mobile && open));
  }
  $("#menu-toggle").addEventListener("click", () => { $("#sidebar").classList.toggle("open"); syncSidebar(); });
  window.addEventListener("resize", syncSidebar); syncSidebar();
  $(".brand").addEventListener("click", event => { event.preventDefault(); navigate("dashboard"); });
  $(".sidebar-help").addEventListener("click", () => navigate("settings"));
  $("#refresh-button").addEventListener("click", async () => { if (pendingAction()) return; try { await refresh(); toast("Saved records refreshed. Your unsent form drafts and notes remain in this tab."); } catch (error) { toast(error.message, true); } });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && $("#sidebar").classList.contains("open")) { $("#sidebar").classList.remove("open"); syncSidebar(); $("#menu-toggle").focus(); } });
  document.addEventListener("click", event => { if (window.innerWidth <= 680 && $("#sidebar").classList.contains("open") && !event.target.closest("#sidebar") && !event.target.closest("#menu-toggle")) { $("#sidebar").classList.remove("open"); syncSidebar(); } });
  window.addEventListener("beforeunload", event => { if (app.drafts.notes.trim() || Object.values(app.drafts.transaction).some(v => String(v).trim()) || Object.keys(app.drafts.setup).length || app.analysisBusy || app.pendingForms || app.reviewBusy || ($("#app-dialog").open && $("#app-dialog").dataset.dirty)) { event.preventDefault(); event.returnValue = ""; } });
  async function boot() {
    try { await refresh(); if (!app.welcomed && !setup().privacy_acknowledged && number(state().revision ?? overview().revision) === 0) welcomeDialog(); }
    catch (error) { $("#connection-status").textContent = "Not connected"; $("#main").replaceChildren(el("div", { class: "error-screen" }, el("div", { class: "empty-icon" }, icon("shield")), el("h1", {}, error.status === 401 || error.status === 403 ? "Open this workspace from its launcher." : "Let’s reconnect your local workspace.") , el("p", {}, error.status === 401 || error.status === 403 ? "The local service requires the private link generated by the launcher. Open that link on this computer. Do not share it; it grants access to this workspace." : error.message), button("Try again", () => boot(), { variant: "secondary" }))); }
  }
  boot();
})();
