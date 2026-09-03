/* Chain check: live server projection -> the real work-console.js gates.
 *
 * Reads the actual `launchAvailable` / `recoveryAvailable` source out of
 * widget/work-console.js (no reimplementation, no fixture) and evaluates it
 * against a payload fetched from a running action host. This is the browser
 * half of #498 verified headlessly: it proves the field the server now emits
 * is the field the UI gate reads, and that the gate flips accordingly.
 *
 * It is NOT a substitute for operator browser acceptance -- it exercises no
 * rendering, focus order, or navigation. It never confirms an action.
 *
 * Usage: node verify_ui_gate_against_live_host.mjs <base-url>
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:8799";
const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "..", "..", "widget", "work-console.js"), "utf8");

function extract(name) {
  const start = source.indexOf("function " + name + "(");
  if (start < 0) throw new Error("function not found in work-console.js: " + name);
  let depth = 0, i = source.indexOf("{", start);
  for (let j = i; j < source.length; j++) {
    if (source[j] === "{") depth++;
    else if (source[j] === "}" && --depth === 0) return source.slice(start, j + 1);
  }
  throw new Error("unbalanced braces for " + name);
}

// The exact production gates and their exact helpers.
const gates = ["correlated", "nextActionKind", "viewAuthorized", "actAuthorized",
               "launchAvailable", "recoveryAvailable"].map(extract).join("\n");
const evaluate = new Function(gates + "\nreturn {launchAvailable, recoveryAvailable, nextActionKind};")();

async function load(what) {
  if (base.startsWith("file:")) {
    const doc = JSON.parse(readFileSync(base.slice(5), "utf8"));
    return doc[what];
  }
  return fetch(base + "/api/" + what).then((r) => r.json());
}
const [ws, caps] = [await load("workstreams"), await load("capabilities")];

// The shape work-console.js holds in `state`: a live (non-synthetic) model
// plus the registered action capabilities the host reports.
const state = { model: { synthetic: false }, capabilities: caps.actions || [] };

let launch = 0, recover = 0;
const rows = [];
for (const x of ws.workstreams) {
  const l = evaluate.launchAvailable(state, x);
  const r = evaluate.recoveryAvailable(state, x);
  if (l) launch++;
  if (r) recover++;
  if (l || r || x.next_action) {
    rows.push({ id: x.id, workflow: x.workflow, kind: evaluate.nextActionKind(x),
                launchAvailable: l, recoveryAvailable: r });
  }
}

console.log("host:", base);
console.log("capabilities:", state.capabilities.map((a) => a.id).join(", "));
console.table(rows);
console.log("launchAvailable true for", launch, "Workstream(s);",
            "recoveryAvailable true for", recover);

// A Workstream must never be offered both, and never one without the field.
for (const row of rows) {
  if (row.launchAvailable && row.recoveryAvailable) throw new Error(row.id + ": both gates open");
  if (row.launchAvailable && row.kind !== "launch") throw new Error(row.id + ": launch without kind");
  if (row.recoveryAvailable && row.kind !== "recover") throw new Error(row.id + ": recover without kind");
}
console.log("OK: no gate opened without its typed next action.");
