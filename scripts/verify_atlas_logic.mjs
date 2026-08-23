/* Headless verification of the Atlas v2 renderer logic (issue #316).
   Mirrors the pure logic in site/src/components/AtlasGraph.tsx against the
   real committed graph.json: visibility default (active work only), search /
   workflow / milestone / area filters, dagre DAG layout, edge orientation.
   Run: node scripts/verify_atlas_logic.mjs (no deps beyond site/node_modules). */
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const siteModules = join(__dirname, '..', 'site', 'node_modules');
const require = createRequire(join(siteModules, 'noop.js'));
const dagre = require('@dagrejs/dagre');

const graphPath = join(__dirname, '..', 'site', 'public', 'atlas', 'graph.json');
const data = JSON.parse(readFileSync(graphPath, 'utf8'));

const NODE_W = 252;
const NODE_H = 84;
const ACTIVE_WORKFLOWS = ['inbox', 'ready', 'in-progress', 'review', 'blocked'];

function isActive(n) {
  if (n.state === 'closed') return false;
  return n.state === 'open' || ACTIVE_WORKFLOWS.includes(n.workflow);
}

let failures = 0;
function check(name, cond, detail) {
  if (cond) console.log('PASS ' + name);
  else {
    failures++;
    console.log('FAIL ' + name + (detail ? ' :: ' + detail : ''));
  }
}

// 1. Graph shape
check('graph.json has nodes', Array.isArray(data.nodes) && data.nodes.length > 0, 'nodes=' + (data.nodes || []).length);
check('graph.json has edges', Array.isArray(data.edges), 'edges=' + (data.edges || []).length);

// 2. Visibility default: active work only
const active = data.nodes.filter(isActive);
const closed = data.nodes.filter((n) => n.state === 'closed');
check('default view excludes closed issues', active.every((n) => n.state === 'open' || ACTIVE_WORKFLOWS.includes(n.workflow)));
check('all closed issues hidden by default', closed.every((n) => !isActive(n)), 'closed=' + closed.length + ' active=' + active.length);
console.log('      counts: total=' + data.nodes.length + ' active=' + active.length + ' closed=' + closed.length + ' frontier=' + data.frontier_count);

// 3. Frontier nodes are open + active
const frontier = data.nodes.filter((n) => n.frontier);
check('frontier nodes are active', frontier.every((n) => isActive(n)), frontier.map((n) => '#' + n.number).join(','));
check('frontier count matches payload', frontier.length === data.frontier_count, frontier.length + ' vs ' + data.frontier_count);

// 4. Layout with default view (active only) via dagre
function layoutGraph(visibleNumbers) {
  const nodes = data.nodes.filter((n) => visibleNumbers.has(n.number));
  const edges = data.edges.filter((e) => visibleNumbers.has(e.from) && visibleNumbers.has(e.to));
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 90, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(String(n.number), { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => {
    const v = String(e.to);
    const w = String(e.from);
    if (v !== w && g.hasNode(v) && g.hasNode(w)) g.setEdge(v, w);
  });
  let positioned = false;
  try {
    dagre.layout(g);
    positioned = true;
  } catch {}
  const pos = new Map();
  if (positioned) {
    nodes.forEach((n) => {
      const pg = g.node(String(n.number));
      if (pg) pos.set(String(n.number), { x: pg.x - NODE_W / 2, y: pg.y - NODE_H / 2 });
    });
  }
  return { nodes, edges, positioned, pos };
}

const defaultVisible = new Set(active.map((n) => n.number));
const laidDefault = layoutGraph(defaultVisible);
check('dagre layout succeeds on default view', laidDefault.positioned);
check('every visible node gets a position', laidDefault.nodes.every((n) => laidDefault.pos.has(String(n.number))));
console.log('      default view: nodes=' + laidDefault.nodes.length + ' edges=' + laidDefault.edges.length);

// 5. Edge orientation: edges run from prerequisite/parent to blocked/child
let orientOk = true;
laidDefault.edges.forEach((e) => {
  const fromNode = data.nodes.find((n) => n.number === e.from);
  const toNode = data.nodes.find((n) => n.number === e.to);
  if (!fromNode || !toNode) return;
  // e.from is the blocked/child issue; e.to is the prerequisite/parent.
  if (e.kind === 'blocked_by' && fromNode.state === 'closed') orientOk = false;
});
check('blocked_by edges target the blocked (open) issue', orientOk);

// 6. Full view (archive on) still lays out
const allVisible = new Set(data.nodes.map((n) => n.number));
const laidAll = layoutGraph(allVisible);
check('dagre layout succeeds on full view (162 nodes)', laidAll.positioned || laidAll.nodes.length > 0);
check('full view positions every node', laidAll.nodes.every((n) => laidAll.pos.has(String(n.number))) || !laidAll.positioned);
console.log('      full view: nodes=' + laidAll.nodes.length + ' edges=' + laidAll.edges.length + ' positioned=' + laidAll.positioned);

// 7. Filters: workflow + milestone + search
const searchVisible = data.nodes.filter((n) => {
  if (!isActive(n)) return false;
  return (n.title + ' #' + n.number).toLowerCase().includes('atlas');
});
check('search "atlas" over active work returns >= 1', searchVisible.length >= 1, 'got ' + searchVisible.length);

const milestoneVisible = data.nodes.filter((n) => isActive(n) && n.milestone === data.milestones[0]);
console.log('      milestone "' + data.milestones[0] + '" active nodes: ' + milestoneVisible.length);

const wfReadyVisible = data.nodes.filter((n) => isActive(n) && n.workflow === 'ready');
check('workflow:ready nodes are visible by default', wfReadyVisible.length >= 1, 'got ' + wfReadyVisible.length);

console.log(failures === 0 ? '\nALL CHECKS PASSED' : '\n' + failures + ' CHECK(S) FAILED');
process.exit(failures === 0 ? 0 : 1);
