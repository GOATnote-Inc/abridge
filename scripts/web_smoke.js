// Web replay smoke: run the page's revision-diff helpers end-to-end against
// the committed golden transcript under a minimal DOM shim. A throw or a
// wrong shape here means the rail would blank at render time — the exact
// failure a venue demo cannot absorb. Invoked by tests/test_web.py.
"use strict";
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const src = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");

function makeNode(tag, cls) {
  return {
    tag, className: cls || "", children: [], _text: "",
    set textContent(v) { this._text = String(v); },
    get textContent() {
      return this._text + this.children.map(c => c.textContent || "").join(" ");
    },
    appendChild(c) { this.children.push(c); return c; },
    setAttribute() {},
  };
}
const documentShim = { createTextNode: (t) => ({ textContent: t }) };

// Extract named top-level functions from the page source by brace matching.
function grab(name) {
  const start = src.indexOf("function " + name + "(");
  if (start < 0) throw new Error("page is missing function " + name);
  let depth = 0, i = src.indexOf("{", start);
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") { depth--; if (depth === 0) break; }
  }
  return src.slice(start, i + 1);
}
const names = ["get", "diffWords", "diffText", "diffRow",
  "triageRevisionDiff", "appealRevisionDiff"];
const code = names.map(grab).join("\n");
const el = (tag, cls, text) => {
  const n = makeNode(tag, cls);
  if (text !== null && text !== undefined) n.textContent = text;
  return n;
};
// Function wrapper (not eval): page functions get el/document as params, so
// strict-mode scoping can't swallow the declarations.
const { triageRevisionDiff, appealRevisionDiff, diffWords } = new Function(
  "el", "document", code + "\nreturn { " + names.join(", ") + " };"
)(el, documentShim);

const t = JSON.parse(
  fs.readFileSync(path.join(ROOT, "web", "demo_transcript.json"), "utf8"));
const flat = (n) => (n.children || []).flatMap(c => [c, ...flat(c)]);
const fail = (msg) => { console.error("SMOKE FAIL: " + msg); process.exit(1); };

// Stage A revision: the under-triage repair must be visible.
const [a0, a1] = t.stage_a.attempts;
const tb = triageRevisionDiff(a0.proposal, a1.proposal);
const dels = flat(tb).filter(n => n.tag === "del").map(n => n._text);
const inss = flat(tb).filter(n => n.tag === "ins").map(n => n._text);
if (!dels.includes(String(a0.proposal.esi_level))) fail("ESI del missing");
if (!inss.includes(String(a1.proposal.esi_level))) fail("ESI ins missing");
const gained = a1.proposal.orders.filter(o => !a0.proposal.orders.includes(o));
for (const o of gained) if (!inss.includes(o)) fail("order ins missing: " + o);

// Act 3 appeal revision: the withheld uncited claim + added authority.
const [p0, p1] = t.stage_c.appeal.attempts;
const ab = appealRevisionDiff(p0.proposal, p1.proposal);
const adels = flat(ab).filter(n => n.tag === "del").map(n => n._text);
const ainss = flat(ab).filter(n => n.tag === "ins").map(n => n._text);
const withheldTexts = p0.proposal.claims
  .filter(c => !p1.proposal.claims.some(k => k.text === c.text))
  .map(c => c.text);
for (const w of withheldTexts)
  if (!adels.some(s => s.includes(w.slice(0, 30)))) fail("withheld claim missing");
const addedAuth = (p1.proposal.authorities_cited || [])
  .filter(x => !(p0.proposal.authorities_cited || []).includes(x));
for (const x of addedAuth) if (!ainss.includes(x)) fail("authority ins missing: " + x);
if (withheldTexts.some(w => !p0.proposal.claims
      .find(c => c.text === w).cites.length)
    && !flat(ab).some(n => n.className === "dwhy"))
  fail("no-citation annotation missing");

// LCS sanity on a known edit.
const kinds = diffWords("the quick brown fox", "the slow brown fox jumps")
  .map(x => x.t).join(",");
if (kinds !== "eq,del,ins,eq,eq,ins") fail("LCS order wrong: " + kinds);

console.log("web smoke OK: both revision diffs render from the golden transcript");
