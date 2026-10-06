/* call-eval static demo. Reads data/demo.json (written by `python -m calleval export-demo`). No build step. */
(function () {
  "use strict";

  var D = null;
  var state = { split: "dev", backend: null, calBackend: null, filter: "all", callId: null };
  var NAMES = { offline: "Rules (offline)", jev: "Jev" };
  var INTENT = { balance: "Balance", payment: "Payment", escrow: "Escrow", payoff: "Payoff quote",
    hardship: "Hardship", dispute: "Dispute", late_fee: "Late fee" };
  var SENT = { happy: "Happy", mild: "Mild", not_happy: "Not happy" };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmt(v, d) { return v == null || isNaN(v) ? "n/a" : Number(v).toFixed(d == null ? 2 : d); }
  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

  /* ---------- theme ---------- */
  (function theme() {
    var saved = null;
    try { saved = localStorage.getItem("calleval-theme"); } catch (e) { /* storage unavailable */ }
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    $("themeBtn").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme");
      if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      var next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("calleval-theme", next); } catch (e) { /* ignore */ }
      if (D) { renderReliability(); renderAgreement(); }
    });
  })();

  /* ---------- tooltip ---------- */
  var tip = document.createElement("div");
  tip.className = "tooltip"; tip.setAttribute("role", "tooltip");
  document.body.appendChild(tip);
  function showTip(e, html) {
    tip.innerHTML = html; tip.classList.add("on");
    var x = Math.min(e.clientX + 12, window.innerWidth - 250), y = e.clientY + 14;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip() { tip.classList.remove("on"); }

  function seg(container, items, current, onPick) {
    container.innerHTML = items.map(function (it) {
      return '<button role="tab" aria-selected="' + (it[0] === current) + '" data-v="' + it[0] + '">' + esc(it[1]) + "</button>";
    }).join("");
    container.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        container.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-selected", "false"); });
        b.setAttribute("aria-selected", "true");
        onPick(b.getAttribute("data-v"));
      });
    });
  }

  /* ---------- tiles ---------- */
  function renderTiles() {
    var p = D.primary, live = D.jev_live_capture, js = D.summary.jev ? D.summary.jev.jev : null;
    var hold = D.agreement.holdout[p], dev = D.agreement.dev[p];
    var ag = (hold && hold.result) || dev, ceil = (hold && hold.ceiling) || D.ceiling;
    var cal = D.calibration[p] || {};
    var off = D.summary.offline;
    var t = [];
    if (js) {
      t.push(["Jev latency per call", fmt(js.call_latency_ms_p50, 0) + "<small> ms p50</small>",
        fmt(js.call_latency_ms_p95, 0) + " ms p95 &middot; " + js.requests_per_call + " requests per call, " +
        fmt(js.request_latency_ms_p50, 0) + " ms each (p50)"]);
    }
    if (live) {
      t.push(["Throughput (Jev)", fmt(live.throughput_calls_per_s, 1) + "<small> calls/s</small>",
        "at concurrency " + live.concurrency + "; 20,000 calls in about " + Math.ceil(20000 / live.throughput_calls_per_s / 60) + " min"]);
    }
    if (off) t.push(["Throughput (rules)", Math.round(off.throughput_calls_per_s).toLocaleString() + "<small> calls/s</small>", "offline, one CPU core, no network"]);
    if (ag) {
      t.push(["Satisfaction agreement", fmt(ag.csat_weighted_kappa_vs_adjudicated, 2) + "<small> wκ</small>",
        "vs adjudicated labels; two humans agree at " + fmt(ceil.csat_weighted_kappa, 2) + " (" + (hold ? "sealed holdout" : "dev") + ", " + NAMES[p] + ")"]);
      t.push(["Sentiment agreement", fmt(ag.sentiment_kappa_vs_adjudicated, 2) + "<small> κ</small>",
        "vs adjudicated labels; two humans agree at " + fmt(ceil.sentiment_kappa, 2) + " (" + (hold ? "sealed holdout" : "dev") + ")"]);
    }
    if (cal.ece_calibrated_oof != null) {
      t.push(["Calibration error", fmt(cal.ece_calibrated_oof, 2) + "<small> survey pts</small>",
        "out of fold, from " + fmt(cal.ece_raw, 2) + " raw; " + cal.n_survey_calls + " survey calls"]);
    }
    if (js) {
      t.push(["Model cost, 20k calls", "$" + fmt(js.cost_per_20k_calls_usd, 2),
        fmt(js.input_tokens_per_call, 0) + " input tokens per call at $" + js.price_per_m_input_usd + "/M (checked " + js.price_checked + ")"]);
    }
    var s = D.summary[p];
    t.push(["Scored vs routed to review", s.scored + "<small> / " + s.review + "</small>", "of " + s.calls + " calls; bad transcripts are never scored"]);
    $("tiles").innerHTML = t.map(function (x) {
      return '<div class="tile"><div class="k">' + x[0] + '</div><div class="v">' + x[1] + '</div><div class="d">' + x[2] + "</div></div>";
    }).join("");
  }

  /* ---------- agreement ---------- */
  function barRows(rows) {
    // rows: [label, value, [lo, hi], colorVar]
    return '<div class="bars">' + rows.map(function (r) {
      var v = Math.max(0, r[1]), lo = r[2] ? r[2][0] : null, hi = r[2] ? r[2][1] : null;
      var svg = '<svg viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden="true">' +
        '<rect x="0" y="5" width="100" height="12" rx="2" fill="' + cssVar("--surface-2") + '"/>' +
        '<rect x="0" y="5" width="' + (v * 100).toFixed(2) + '" height="12" rx="2" fill="' + cssVar(r[3]) + '"/>' +
        (lo != null ? '<line x1="' + lo * 100 + '" x2="' + hi * 100 + '" y1="11" y2="11" stroke="' + cssVar("--text") + '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
          '<line x1="' + lo * 100 + '" x2="' + lo * 100 + '" y1="7" y2="15" stroke="' + cssVar("--text") + '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
          '<line x1="' + hi * 100 + '" x2="' + hi * 100 + '" y1="7" y2="15" stroke="' + cssVar("--text") + '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' : "") +
        "</svg>";
      return '<div class="bar-row" data-tip="' + esc(r[0] + ": " + fmt(r[1], 3) + (lo != null ? " (95% CI " + fmt(lo, 3) + " to " + fmt(hi, 3) + ")" : "")) + '">' +
        '<span class="lab">' + esc(r[0]) + '</span><span class="bar-track">' + svg + '</span><span class="val">' + fmt(r[1], 2) + "</span></div>";
    }).join("") + '<div class="bar-row"><span></span><span class="fine" style="display:flex;justify-content:space-between"><span>0</span><span>0.5</span><span>1.0</span></span><span></span></div></div>';
  }

  function attachBarTips(root) {
    root.querySelectorAll("[data-tip]").forEach(function (el) {
      el.addEventListener("mousemove", function (e) { showTip(e, esc(el.getAttribute("data-tip"))); });
      el.addEventListener("mouseleave", hideTip);
    });
  }

  function splitData(r) {
    if (state.split === "dev") return { m: D.agreement.dev[r], ceil: D.ceiling };
    var h = D.agreement.holdout[r];
    return h ? { m: h.result, ceil: h.ceiling } : null;
  }

  function renderAgreement() {
    var csat = [], sent = [], ceil = null, notes = [];
    var colors = { jev: "--s1", offline: "--s2" };
    D.runs.slice().reverse().forEach(function (r) {
      var x = splitData(r);
      if (!x || !x.m) return;
      ceil = x.ceil;
      csat.push([NAMES[r], x.m.csat_weighted_kappa_vs_adjudicated, x.m.csat_weighted_kappa_vs_adjudicated_ci, colors[r]]);
      sent.push([NAMES[r], x.m.sentiment_kappa_vs_adjudicated, x.m.sentiment_kappa_vs_adjudicated_ci, colors[r]]);
      notes.push(NAMES[r] + ": coverage " + Math.round(x.m.coverage * 100) + "%, vs a single annotator wκ " +
        fmt(x.m.csat_weighted_kappa_vs_annotators) + " / κ " + fmt(x.m.sentiment_kappa_vs_annotators));
    });
    if (ceil) {
      csat.unshift(["Annotator A vs B", ceil.csat_weighted_kappa, ceil.csat_weighted_kappa_ci, "--muted"]);
      sent.unshift(["Annotator A vs B", ceil.sentiment_kappa, ceil.sentiment_kappa_ci, "--muted"]);
    }
    $("agreeCsat").innerHTML = csat.length ? barRows(csat) : '<p class="empty">Not evaluated on this split.</p>';
    $("agreeSent").innerHTML = sent.length ? barRows(sent) : '<p class="empty">Not evaluated on this split.</p>';
    attachBarTips($("agreeCsat")); attachBarTips($("agreeSent"));
    $("agreeNote").innerHTML = "Bars compare each system with the adjudicated label; the like-for-like comparison with the ceiling is a system against one annotator. " +
      esc(notes.join(". ")) + ". Coverage is the share of labelled calls that passed the quality gate and were scored.";
    renderConfusions();
  }

  function cmTable(title, cm, names) {
    var max = 0; cm.matrix.forEach(function (row) { row.forEach(function (v) { max = Math.max(max, v); }); });
    var steps = ["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"];
    var h = '<div><h3>' + esc(title) + '</h3><table class="cm"><caption class="sr">rows adjudicated, columns predicted</caption><tr><th></th>' +
      cm.labels.map(function (l) { return "<th>" + esc(names ? names[l] : l) + "</th>"; }).join("") + "</tr>";
    cm.matrix.forEach(function (row, i) {
      h += "<tr><th>" + esc(names ? names[cm.labels[i]] : cm.labels[i]) + "</th>" + row.map(function (v) {
        var k = v === 0 ? 0 : 1 + Math.min(5, Math.floor(5 * v / max));
        return '<td class="' + (k >= 4 ? "dark" : "") + '" style="background:var(' + steps[k] + ')">' + v + "</td>";
      }).join("") + "</tr>";
    });
    return h + '</table><p class="fine">Rows: adjudicated label. Columns: predicted.</p></div>';
  }

  function renderConfusions() {
    var x = splitData(D.primary);
    if (!x || !x.m) { $("confusions").innerHTML = ""; return; }
    var sn = { happy: "hap", mild: "mild", not_happy: "not" };
    $("confusions").innerHTML = cmTable(NAMES[D.primary] + ": satisfaction", x.m.confusion_csat) +
      cmTable(NAMES[D.primary] + ": sentiment", x.m.confusion_sentiment, sn);
    var nf = D.noise_floor || {}, parts = [];
    Object.keys(nf).forEach(function (k) {
      var n = nf[k];
      parts.push(esc(n.runs.join(" vs ")) + " on " + n.n_calls + " dev calls: " + Math.round(n.csat_identical * 1000) / 10 +
        "% identical satisfaction, " + Math.round(n.sentiment_identical * 1000) / 10 + "% identical sentiment, kappa spread " + n.csat_kappa_spread);
    });
    $("noise").innerHTML = parts.length ? "<p><b>Run-to-run noise floor</b> (same model, same questions, run twice): " + parts.join("; ") +
      ". Sampling noise is larger: see the 95% bootstrap intervals above. A change has to clear both to count.</p>" : "";
  }

  /* ---------- quadrant ---------- */
  function renderQuadrant() {
    var q = D.quadrant[D.primary], bands = [["high", "4–5"], ["mid", "3"], ["low", "1–2"]];
    var sents = ["happy", "mild", "not_happy"], max = 0;
    bands.forEach(function (b) { sents.forEach(function (s) { max = Math.max(max, q[b[0]][s]); }); });
    var steps = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5"];
    var h = '<div class="quad"><div></div>' + sents.map(function (s) { return '<div class="h">' + SENT[s] + "</div>"; }).join("");
    bands.forEach(function (b) {
      h += '<div class="rh">' + b[1] + "</div>";
      sents.forEach(function (s) {
        var v = q[b[0]][s], k = Math.min(4, Math.floor(4.999 * v / max));
        var risk = b[0] === "low" && s !== "not_happy";
        h += '<div class="cell' + (risk ? " risk" : "") + '" style="background:var(' + steps[k] + ');color:' + (k >= 3 ? "#fff" : "var(--text)") +
          '" data-tip="' + esc("Satisfaction " + b[1] + ", sentiment " + SENT[s] + ": " + v + " calls") + '"><b>' + v + "</b><span>calls</span></div>";
      });
    });
    h += '</div><div class="quad-axis">Rows: scored satisfaction. Columns: expressed sentiment.</div>';
    $("quadChart").innerHTML = h;
    $("quadChart").classList.add("chart");
    attachBarTips($("quadChart"));
    $("quadBackend").textContent = "(" + NAMES[D.primary] + ", " + D.summary[D.primary].scored + " scored calls)";
    var ids = D.churn_risk_calls;
    $("churnCount").textContent = ids.length;
    $("churnList").innerHTML = ids.map(function (id) { return '<li><button type="button" data-id="' + id + '">' + id + "</button></li>"; }).join("");
    $("churnList").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () { openCall(b.getAttribute("data-id"), "churn"); });
    });
  }

  /* ---------- explorer ---------- */
  var byId = {};
  function predOf(c, r) { return c.pred[r || state.backend]; }

  function matches(c) {
    var p = predOf(c);
    switch (state.filter) {
      case "churn": return p.status === "scored" && p.churn;
      case "review": return p.status !== "scored" || (p.review && p.review.length);
      case "dev": return !!c.gold;
      case "multi": return p.status === "scored" && p.intents.length > 1;
      case "disagree":
        var a = c.pred.offline, b = c.pred.jev;
        return a && b && a.status === "scored" && b.status === "scored" && (a.csat !== b.csat || a.sentiment !== b.sentiment);
      default: return true;
    }
  }

  function renderList() {
    var list = D.calls.filter(matches);
    $("callList").innerHTML = list.length ? list.map(function (c) {
      var p = predOf(c), right;
      if (p.status !== "scored") right = '<span class="badge rev">review</span>';
      else right = '<span class="score-pill" title="satisfaction">' + p.csat + "</span>";
      var meta = p.status === "scored" ? SENT[p.sentiment] + " · " + p.intents.map(function (x) { return INTENT[x.intent]; }).join(", ") : (p.review[0] || "");
      return '<li><button type="button" data-id="' + c.id + '" aria-current="' + (c.id === state.callId) + '"><span class="cid">' + c.id +
        '</span><span class="meta">' + esc(meta) + "</span>" + right + "</button></li>";
    }).join("") : '<li class="empty">No calls match.</li>';
    $("callList").querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () { state.callId = b.getAttribute("data-id"); renderList(); renderDetail(); });
    });
  }

  function cls(kind) {
    if (kind === "outcome") return "outcome";
    if (kind === "feeling-positive") return "pos";
    if (kind === "feeling-negative") return "neg";
    if (kind === "feeling-neutral") return "neu";
    return "effort";
  }
  var PRIORITY = { outcome: 5, neg: 4, effort: 3, pos: 2, neu: 1 };

  function highlight(text, spans) {
    if (!spans.length) return esc(text);
    var cuts = [0, text.length];
    spans.forEach(function (s) { cuts.push(s[1], s[2]); });
    cuts = Array.from(new Set(cuts)).filter(function (x) { return x >= 0 && x <= text.length; }).sort(function (a, b) { return a - b; });
    var out = "";
    for (var i = 0; i < cuts.length - 1; i++) {
      var a = cuts[i], b = cuts[i + 1], piece = text.slice(a, b);
      var cover = spans.filter(function (s) { return s[1] <= a && s[2] >= b; });
      if (!cover.length) { out += esc(piece); continue; }
      var best = cover.slice().sort(function (x, y) { return PRIORITY[cls(y[3])] - PRIORITY[cls(x[3])]; })[0];
      var title = cover.map(function (s) { return s[3].replace("feeling-", "feeling: ") + " (" + (INTENT[s[4]] || s[4]) + ")"; }).join("; ");
      out += '<mark class="' + cls(best[3]) + '" title="' + esc(title) + '">' + esc(piece) + "</mark>";
    }
    return out;
  }

  function renderDetail() {
    var c = byId[state.callId];
    if (!c) { $("callDetail").innerHTML = '<p class="empty">Select a call.</p>'; return; }
    var p = predOf(c), h = "";
    h += '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between">' +
      '<h3 style="margin:0;font-size:18px;font-family:var(--mono)">' + c.id + "</h3>" +
      '<div class="kv"><span><b>Agent</b> ' + c.agent + "</span><span><b>Date</b> " + c.date + "</span><span><b>Length</b> " +
      Math.round(c.dur / 60) + " min</span>" + (c.survey ? "<span><b>Survey</b> " + c.survey + "/5</span>" : "") + "</div></div>";
    if (c.gold) {
      h += '<div class="kv" style="margin-top:6px"><span><b>Human labels</b> A: ' + c.gold.a[0] + " / " + SENT[c.gold.a[1]] +
        " &middot; B: " + c.gold.b[0] + " / " + SENT[c.gold.b[1]] + " &middot; adjudicated: " + c.gold.adj[0] + " / " + SENT[c.gold.adj[1]] + "</span></div>";
    }
    var spans = [];
    if (p.status !== "scored") {
      h += '<div class="gate-box"><b>Not scored. Routed to human review:</b><ul>' + p.review.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("") + "</ul></div>";
    } else {
      spans = p.spans;
      h += '<div class="scores"><div class="scorebox"><div class="kv"><b>Satisfaction</b>' + (p.churn ? '<span class="badge risk">churn risk</span>' : "") + "</div>" +
        '<div class="big">' + p.csat + '<span class="muted" style="font-size:14px;font-weight:500"> / 5 &middot; raw ' + fmt(p.raw) +
        (p.cal != null ? " &middot; calibrated " + fmt(p.cal) : "") + "</span></div>" +
        '<div class="why">' + esc(p.sx) + "</div></div>" +
        '<div class="scorebox"><div class="kv"><b>Sentiment</b></div><div class="big">' + SENT[p.sentiment] + "</div>" +
        '<div class="why">' + esc(p.tx) + "</div></div></div>";
      h += '<div class="intents">' + p.intents.map(function (x) {
        return '<div class="intent-row"><b>' + esc(INTENT[x.intent]) + '</b><span class="res-' + x.resolved + '">' + x.resolved +
          '</span><span class="why muted">turns ' + x.segment[0] + "–" + x.segment[1] + " &middot; intent score " + fmt(x.sat, 1) +
          " &middot; confidence " + fmt(x.conf) + "</span></div>";
      }).join("") + "</div>";
      if (p.review && p.review.length) h += '<div class="gate-box"><b>Flagged for a look:</b> ' + esc(p.review.join("; ")) + "</div>";
    }
    if (c.gate.reasons.length === 0 && p.status === "scored") {
      h += '<div class="legend"><span><i class="sw outcome"></i>outcome</span><span><i class="sw effort"></i>effort (repeat, hold, transfer, callback)</span>' +
        '<span><i class="sw pos"></i>positive feeling</span><span><i class="sw neu"></i>neutral</span><span><i class="sw neg"></i>negative feeling</span></div>';
    }
    var segs = p.status === "scored" ? p.intents.map(function (x) { return x.segment; }) : [];
    h += '<div class="transcript">' + c.turns.map(function (t, i) {
      var mine = spans.filter(function (s) { return s[0] === i; });
      var inSeg = segs.some(function (sg) { return i >= sg[0] && i <= sg[1]; });
      var who = t[0] === "A" ? "agent" : t[0] === "C" ? "caller" : "unknown";
      return '<div class="turn ' + who + (inSeg ? " in-seg" : "") + '"><span class="ix">' + i + '</span><span class="who">' + who +
        '</span><span class="tx">' + highlight(t[1], mine) + "</span></div>";
    }).join("") + "</div>";
    if (p.v) {
      h += '<p class="fine" style="margin-top:14px">Row versions: ' + esc(p.v.extractor_backend + " · " + p.v.model_id + " · questions " +
        p.v.question_version + " · " + p.v.scoring_version + " · code " + p.v.code_version) + "</p>";
    }
    $("callDetail").innerHTML = h;
  }

  function openCall(id, filter) {
    state.callId = id;
    if (filter) { state.filter = filter; $("callFilter").value = filter; }
    renderList(); renderDetail();
    document.getElementById("explorer").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  /* ---------- reliability ---------- */
  function renderReliability() {
    var cal = D.calibration[state.calBackend];
    if (!cal) { $("relChart").innerHTML = '<p class="empty">No calibration for this run.</p>'; $("calFacts").innerHTML = ""; return; }
    var W = 420, H = 300, m = { l: 40, r: 14, t: 12, b: 36 };
    var x = function (v) { return m.l + (v - 1) / 4 * (W - m.l - m.r); };
    var y = function (v) { return H - m.b - (v - 1) / 4 * (H - m.t - m.b); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Reliability diagram">';
    for (var g = 1; g <= 5; g++) {
      s += '<line class="gridline" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y(g) + '" y2="' + y(g) + '"/>';
      s += '<text x="' + (m.l - 8) + '" y="' + (y(g) + 4) + '" text-anchor="end">' + g + "</text>";
      s += '<text x="' + x(g) + '" y="' + (H - m.b + 16) + '" text-anchor="middle">' + g + "</text>";
    }
    s += '<text x="' + ((m.l + W - m.r) / 2) + '" y="' + (H - 4) + '" text-anchor="middle">mean predicted score</text>';
    s += '<text transform="rotate(-90)" x="' + (-(H - m.b + m.t) / 2) + '" y="11" text-anchor="middle">mean survey score</text>';
    s += '<line x1="' + x(1) + '" y1="' + y(1) + '" x2="' + x(5) + '" y2="' + y(5) + '" stroke="' + cssVar("--muted") + '" stroke-width="1.5" stroke-dasharray="4 4"/>';
    var series = [["reliability_raw", "--s2", "Raw score"], ["reliability_calibrated", "--s1", "Calibrated (out of fold)"]];
    var dots = [];
    series.forEach(function (se) {
      var pts = cal[se[0]], col = cssVar(se[1]);
      s += '<polyline fill="none" stroke="' + col + '" stroke-width="2" stroke-linejoin="round" points="' +
        pts.map(function (p) { return x(p.mean_pred) + "," + y(p.mean_obs); }).join(" ") + '"/>';
      pts.forEach(function (p) {
        dots.push('<circle cx="' + x(p.mean_pred) + '" cy="' + y(p.mean_obs) + '" r="5" fill="' + col + '" stroke="' + cssVar("--surface") +
          '" stroke-width="2" data-tip="' + esc(se[2] + ", band " + p.bin + ": predicted " + fmt(p.mean_pred) + ", survey " + fmt(p.mean_obs) + ", n=" + p.n) + '"/>' +
          '<circle cx="' + x(p.mean_pred) + '" cy="' + y(p.mean_obs) + '" r="12" fill="transparent" data-tip="' +
          esc(se[2] + ", band " + p.bin + ": predicted " + fmt(p.mean_pred) + ", survey " + fmt(p.mean_obs) + ", n=" + p.n) + '"/>');
      });
    });
    s += dots.join("") + "</svg>";
    s += '<div class="chart-legend"><span><i style="background:' + cssVar("--s2") + '"></i>Raw score</span><span><i style="background:' + cssVar("--s1") +
      '"></i>Calibrated (out of fold)</span><span><i style="background:' + cssVar("--muted") + '"></i>Perfect calibration</span></div>';
    $("relChart").innerHTML = s; $("relChart").classList.add("chart");
    attachBarTips($("relChart"));
    var rr = cal.response_rate_by_bucket || {};
    $("calFacts").innerHTML = '<div class="facts">' +
      fact("Error, raw", fmt(cal.ece_raw), "survey points, count-weighted across bands") +
      fact("Error, calibrated", fmt(cal.ece_calibrated_oof), "5-fold out of fold, response-bias weighted") +
      fact("Without bias weights", fmt(cal.ece_calibrated_oof_unweighted), "same fit, every answer weighted equally") +
      fact("Survey calls used", cal.n_survey_calls, "sealed holdout excluded from the fit") +
      fact("Mean survey, as observed", fmt(cal.survey_mean_observed), "skewed down: unhappy callers answer more") +
      fact("Mean survey, re-weighted", fmt(cal.survey_mean_weighted), "inverse response-rate weights") +
      "</div><p class=\"fine\">Response rate by raw-score band (1 to 5): " + Object.keys(rr).map(function (k) { return Math.round(rr[k] * 100) + "%"; }).join(", ") +
      ". With fewer than a hundred survey answers the fitted map is noisy: if calibrated error is not clearly below raw, publish buckets, not numbers.</p>";
  }
  function fact(k, v, d) { return '<div class="fact"><div class="k">' + k + '</div><div class="v">' + v + '</div><div class="d">' + d + "</div></div>"; }

  /* ---------- review + rollups ---------- */
  function renderReview() {
    var rc = D.review_reason_counts, max = Math.max.apply(null, Object.values(rc).concat([1]));
    $("reasonCounts").innerHTML = "<h3>Why calls are in the queue <span class=\"muted\">(" + D.review_queue.length + " calls, " + NAMES[D.primary] + ")</span></h3>" +
      Object.keys(rc).map(function (k) {
        return '<div class="reason-bar"><span>' + esc(k) + '</span><span><div class="rb" style="width:' + (100 * rc[k] / max) + '%"></div></span><span class="n">' + rc[k] + "</span></div>";
      }).join("");
    var t = "<thead><tr><th>Call</th><th>Agent</th><th>Status</th><th>Reasons</th></tr></thead><tbody>" +
      D.review_queue.map(function (q) {
        return '<tr class="clickable" data-id="' + q.call_id + '"><td style="font-family:var(--mono)">' + q.call_id + "</td><td>" + q.agent_id + "</td><td>" +
          esc(q.kind) + "</td><td>" + esc(q.reasons.join("; ")) + "</td></tr>";
      }).join("") + "</tbody>";
    $("reviewTable").innerHTML = t;
    $("reviewTable").querySelectorAll("tr.clickable").forEach(function (tr) {
      tr.addEventListener("click", function () { openCall(tr.getAttribute("data-id"), "review"); });
    });
  }

  function renderRollups() {
    $("agentTable").innerHTML = "<thead><tr><th>Agent</th><th class=num>Scored</th><th class=num>Mean sat.</th><th class=num>Calibrated</th><th class=num>Unresolved</th><th class=num>Not happy</th><th class=num>Churn risk</th></tr></thead><tbody>" +
      D.by_agent.map(function (a) {
        return "<tr><td>" + a.agent_id + "</td><td class=num>" + a.scored + "</td><td class=num>" + fmt(a.mean_csat) + "</td><td class=num>" + fmt(a.mean_calibrated) +
          "</td><td class=num>" + Math.round(a.unresolved_intent_share * 100) + "%</td><td class=num>" + Math.round(a.not_happy_share * 100) + "%</td><td class=num>" + a.churn_risk + "</td></tr>";
      }).join("") + "</tbody>";
    $("intentTable").innerHTML = "<thead><tr><th>Intent</th><th class=num>n</th><th class=num>Resolved</th><th class=num>Partial</th><th class=num>No</th><th class=num>Mean score</th></tr></thead><tbody>" +
      D.by_intent.map(function (i) {
        return "<tr><td>" + esc(i.label) + "</td><td class=num>" + i.n + "</td><td class=num>" + Math.round(i.resolved_yes * 100) + "%</td><td class=num>" +
          Math.round(i.resolved_partial * 100) + "%</td><td class=num>" + Math.round(i.resolved_no * 100) + "%</td><td class=num>" + fmt(i.mean_intent_satisfaction, 1) + "</td></tr>";
      }).join("") + "</tbody>";
  }

  function renderVersions() {
    $("versions").textContent = "Generated " + D.generated_at + " from seed " + D.seed + ". " + D.runs.map(function (r) {
      var v = D.versions[r];
      return NAMES[r] + ": " + v.model_id + ", questions " + v.question_version + ", " + v.scoring_version + ", " + v.gate_version + ", code " + v.code_version;
    }).join(" | ");
  }

  /* ---------- boot ---------- */
  fetch("data/demo.json").then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (d) {
    D = d;
    D.calls.forEach(function (c) { byId[c.id] = c; });
    state.backend = D.primary; state.calBackend = D.primary;
    renderTiles();
    seg($("splitTabs"), [["dev", "Dev (200)"], ["holdout", "Sealed holdout (100)"]], state.split, function (v) { state.split = v; renderAgreement(); });
    renderAgreement();
    renderQuadrant();
    seg($("backendTabs"), D.runs.map(function (r) { return [r, NAMES[r]]; }), state.backend, function (v) { state.backend = v; renderList(); renderDetail(); });
    seg($("calTabs"), D.runs.map(function (r) { return [r, NAMES[r]]; }), state.calBackend, function (v) { state.calBackend = v; renderReliability(); });
    $("callFilter").addEventListener("change", function (e) { state.filter = e.target.value; renderList(); });
    state.callId = D.churn_risk_calls[0] || D.calls[0].id;
    renderList(); renderDetail();
    renderReliability(); renderReview(); renderRollups(); renderVersions();
  }).catch(function (e) {
    document.querySelector("main").insertAdjacentHTML("afterbegin",
      '<div class="wrap"><p class="card" style="margin-top:20px">Could not load data/demo.json (' + esc(e.message) +
      '). Serve this folder over HTTP, for example <code>python -m http.server -d docs</code>.</p></div>');
  });
})();
