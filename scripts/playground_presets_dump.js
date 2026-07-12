// Extract the playground's preset arrays FROM THE PAGE (single source) and
// emit the exact request bodies its buttons would send, as canonical JSON.
// The body-building below mirrors the page's goT/goM/coveragePreset handlers;
// keep them in sync (the recorded-mode test regenerates and byte-compares).
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const src = fs.readFileSync(path.join(ROOT, "web", "playground.html"), "utf8");

function grabArray(name) {
  const start = src.indexOf("var " + name + "=[");
  if (start < 0) throw new Error("missing " + name);
  let i = src.indexOf("[", start), depth = 0;
  const a0 = i;
  for (; i < src.length; i++) {
    if (src[i] === "[") depth++;
    else if (src[i] === "]") { depth--; if (depth === 0) break; }
  }
  // The arrays are JS literals (quoted strings, object literals) — evaluate
  // them in isolation; no page code runs.
  return new Function("return " + src.slice(a0, i + 1))();
}

const TP = grabArray("TP");
const MP = grabArray("MP");

// The page's own canonicalizer (extracted, not reimplemented) — the emitted
// key is exactly what the running page will look up at fallback time.
function grabFn(name) {
  const start = src.indexOf("function " + name + "(");
  if (start < 0) throw new Error("missing " + name);
  let i = src.indexOf("{", start), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") { depth--; if (depth === 0) break; }
  }
  return new Function("return " + src.slice(start, i + 1))();
}
const stableStr = grabFn("stableStr");

const num = (v) => (String(v).trim() === "" ? null : Number(v));

function triageBody(v) {
  const enc = {
    encounter_id: "PLAY", chief_complaint: v.cc, age_years: num(v.age),
    vitals: { hr: num(v.hr), rr: num(v.rr), spo2: num(v.spo2),
              sbp: num(v.sbp), dbp: num(v.dbp), temp_c: num(v.temp),
              pain: num(v.pain), gcs: num(v.gcs) },
  };
  for (const k of Object.keys(enc.vitals))
    if (enc.vitals[k] === null) delete enc.vitals[k];
  if (String(v.tx).trim()) enc.transcript = v.tx;
  const orders = v.orders.split(",").map(s => s.trim()).filter(Boolean);
  const prop = { esi_level: v.esi ? Number(v.esi) : null, orders,
                 disposition: v.dispo, rationale: v.rat || null };
  return { path: "/supervise/triage", body: { encounter: enc, proposed: prop } };
}

function chart(kind) {
  if (kind === "none") return { orders: [], results: [], escalations: [] };
  if (kind === "normal") return { orders: [{ id: "ord-cbc", name: "cbc" }],
    results: [{ id: "res-cbc", order_id: "ord-cbc", name: "cbc",
      value: "normal", flag: "normal", status: "final", released: true,
      viewed: false, discussed: false }], escalations: [] };
  const trop = (disc) => ({ orders: [{ id: "ord-troponin", name: "troponin" }],
    results: [{ id: "res-troponin", order_id: "ord-troponin", name: "troponin",
      value: "0.31", flag: "critical", status: "final", released: true,
      viewed: true, discussed: disc }], escalations: [] });
  if (kind === "critical") return trop(false);
  if (kind === "discussed") return trop(true);
  const c = trop(true); c.escalations = ["patient viewed critical troponin"];
  return c;
}

function messageBody(aud, chartKind, text) {
  const c = chart(chartKind);
  return { path: "/supervise/rendering",
           body: { audience: aud, text, refs: c.results.map(r => r.id),
                   chart: c } };
}

const out = [];
for (const [label, v] of TP) out.push({ label, ...triageBody(v) });
for (const [label, aud, kind, text] of MP)
  out.push({ label, ...messageBody(aud, kind, text) });
for (const name of ["vague_denial", "unsupported_claim", "auto_deny"])
  out.push({ label: "coverage:" + name, path: "/coverage/preset",
             body: { name } });
for (const p of out) p.page_key = p.path + "|" + stableStr(p.body);

process.stdout.write(JSON.stringify(out));
