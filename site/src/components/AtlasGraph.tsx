/* Visual Atlas v2 renderer (issue #316): interactive React Flow graph.
   Fetches /atlas/graph.json (emitted by scripts/atlas_sync.py --emit-graph),
   lays out the visible subgraph with dagre (layered DAG: prerequisites and
   parents to the left, dependents and children to the right), renders
   blocked_by / part_of edges as directed links, highlights the actionable
   frontier, and defaults to active work only (open issues and non-done
   workflow states) with the closed archive behind a toggle.
   Content-free: never emits issue bodies, prompts, or reasoning. */
import { useEffect, useMemo, useRef, useState } from 'react';
import dagre from '@dagrejs/dagre';
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge as RFEdge,
  type Node as RFNode,
  type NodeProps,
} from '@xyflow/react';
// React Flow's base styles are imported once in the hosting Astro page
// (src/pages/atlas.astro); the island itself stays style-free so it can be
// type-checked and bundled in isolation.

export type AtlasNodeData = {
  number: number;
  title: string;
  state: 'open' | 'closed';
  area: string;
  frontier: boolean;
  in_progress: boolean;
  milestone: string | null;
  work_kind: string;
  workflow: string;
} & Record<string, unknown>;

interface AtlasGraphData {
  drift_count: number;
  edges: Array<{ from: number; to: number; kind: 'blocked_by' | 'part_of' }>;
  frontier_count: number;
  milestones: string[];
  nodes: AtlasNodeData[];
  repo: string;
  schema_version: number;
  sync_time: string;
}

const NODE_W = 252;
const NODE_H = 84;

const WF_LABEL: Record<string, string> = {
  inbox: 'inbox',
  ready: 'ready',
  'in-progress': 'in progress',
  review: 'review',
  blocked: 'blocked',
  done: 'done',
  none: 'no label',
};

const WF_COLOR: Record<string, string> = {
  inbox: '#d4c5f9',
  ready: '#3fb950',
  'in-progress': '#d29922',
  review: '#1d76db',
  blocked: '#f85149',
  done: '#56617a',
  none: '#8792a8',
};

const ACTIVE_WORKFLOWS = ['inbox', 'ready', 'in-progress', 'review', 'blocked'];

function isActive(n: AtlasNodeData): boolean {
  if (n.state === 'closed') return false;
  return n.state === 'open' || ACTIVE_WORKFLOWS.includes(n.workflow);
}

/* --- custom node ------------------------------------------------------- */

function AtlasNode({ data }: NodeProps<RFNode<AtlasNodeData>>) {
  const d = data as AtlasNodeData;
  const color = WF_COLOR[d.workflow] || WF_COLOR.none;
  const metaParts = ['#' + d.number, WF_LABEL[d.workflow] || d.workflow];
  if (d.state === 'closed') metaParts.push('closed');
  if (d.work_kind && d.work_kind !== 'delivery') metaParts.push(d.work_kind);
  return (
    <div
      className={
        'atlas-node wf-' + d.workflow + (d.frontier ? ' frontier' : '') + (d.state === 'closed' ? ' closed' : '')
      }
      style={{ width: NODE_W, height: NODE_H }}
      title={d.title + ' (#' + d.number + ') - click to open on GitHub'}
    >
      <span className="atlas-node-title" style={{ borderColor: color }}>
        {d.title || '#' + d.number}
      </span>
      <span className="atlas-node-meta">{metaParts.join(' · ')}</span>
      {d.frontier && <span className="atlas-node-frontier">frontier</span>}
    </div>
  );
}

const nodeTypes = { atlas: AtlasNode };

/* --- dagre layout ------------------------------------------------------ */

interface LayedOut {
  nodes: RFNode<AtlasNodeData>[];
  edges: RFEdge[];
}

function layoutGraph(data: AtlasGraphData, visibleNumbers: Set<number>): LayedOut {
  const nodes = data.nodes.filter((n) => visibleNumbers.has(n.number));
  const edges = data.edges.filter((e) => visibleNumbers.has(e.from) && visibleNumbers.has(e.to));

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'LR', nodesep: 30, ranksep: 90, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(String(n.number), { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => {
    // Orient prerequisites/parents (e.to) to the left, dependents/children (e.from) to the right.
    const v = String(e.to);
    const w = String(e.from);
    if (v !== w && g.hasNode(v) && g.hasNode(w)) g.setEdge(v, w);
  });

  let positioned = false;
  try {
    dagre.layout(g);
    positioned = true;
  } catch {
    // Graph not a DAG (drift) - fall back to a plain grid below.
  }

  const pos = new Map<string, { x: number; y: number }>();
  if (positioned) {
    nodes.forEach((n) => {
      const pg = g.node(String(n.number));
      if (pg) pos.set(String(n.number), { x: pg.x - NODE_W / 2, y: pg.y - NODE_H / 2 });
    });
  } else {
    nodes.forEach((n, i) => {
      pos.set(String(n.number), { x: 24 + (i % 5) * (NODE_W + 32), y: 24 + Math.floor(i / 5) * (NODE_H + 32) });
    });
  }

  const rfNodes: RFNode<AtlasNodeData>[] = nodes.map((n) => ({
    id: String(n.number),
    type: 'atlas',
    position: pos.get(String(n.number)) || { x: 0, y: 0 },
    data: n,
  }));

  const rfEdges: RFEdge[] = edges.map((e) => {
    const blocked = e.kind === 'blocked_by';
    return {
      id: e.kind + '-' + e.from + '-' + e.to,
      source: String(e.to), // prerequisite / parent
      target: String(e.from), // blocked / child
      type: 'smoothstep',
      className: 'atlas-edge ' + (blocked ? 'blocked-by' : 'part-of'),
      markerEnd: blocked ? 'arrow-red' : 'arrow-blue',
      label: blocked ? 'blocks' : 'contains',
      labelStyle: { fontSize: 10, fill: blocked ? '#ff5c5c' : '#7c8fff' },
      style: blocked
        ? { stroke: '#ff5c5c', strokeDasharray: '6 3', strokeWidth: 1.6 }
        : { stroke: '#7c8fff', strokeWidth: 1.3, opacity: 0.75 },
    };
  });

  return { nodes: rfNodes, edges: rfEdges };
}

/* --- flow body --------------------------------------------------------- */

function Flow({ data, visibleNumbers }: { data: AtlasGraphData; visibleNumbers: Set<number> }) {
  const { fitView } = useReactFlow();
  const laid = useMemo(() => layoutGraph(data, visibleNumbers), [data, visibleNumbers]);

  useEffect(() => {
    const t = window.setTimeout(() => fitView({ padding: 0.25, duration: 350 }), 60);
    return () => window.clearTimeout(t);
  }, [laid, fitView]);

  return (
    <ReactFlow
      nodes={laid.nodes}
      edges={laid.edges}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.25 }}
      minZoom={0.15}
      maxZoom={2.5}
      proOptions={{ hideAttribution: false }}
      onNodeClick={(_e, n) => {
        const d = n.data as AtlasNodeData;
        window.open('https://github.com/' + data.repo + '/issues/' + d.number, '_blank');
      }}
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#243049" />
      <Controls showInteractive={false} />
      <MiniMap
        pannable
        zoomable
        nodeColor={(n) => (n.data && (n.data as AtlasNodeData).frontier ? '#4d6bfe' : WF_COLOR[(n.data as AtlasNodeData).workflow] || '#56617a')}
        maskColor="rgba(8,11,20,0.72)"
      />
      <defs>
        <marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#ff5c5c" />
        </marker>
        <marker id="arrow-blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#7c8fff" />
        </marker>
      </defs>
    </ReactFlow>
  );
}

/* --- island root -------------------------------------------------------- */

export default function AtlasGraph() {
  const [data, setData] = useState<AtlasGraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showArchive, setShowArchive] = useState(false);
  const [query, setQuery] = useState('');
  const [wfFilter, setWfFilter] = useState<Set<string>>(new Set());
  const [milestone, setMilestone] = useState<string>('__all__');
  const [area, setArea] = useState<string>('__all__');
  const searchBox = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch('./graph.json', { headers: { Accept: 'application/json' } })
      .then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then((g: AtlasGraphData) => {
        if (!g || !Array.isArray(g.nodes) || g.nodes.length === 0) {
          setError('The graph file exists but contains no nodes yet. It will populate after the next Atlas sync.');
          return;
        }
        setData(g);
      })
      .catch((e) => {
        setError(
          'Could not load the Atlas graph (' + (e && e.message ? e.message : 'network error') +
            '). It is generated by the daily Atlas sync; check back after the next sync.'
        );
      });
  }, []);

  const visibleNumbers = useMemo(() => {
    if (!data) return new Set<number>();
    const q = query.trim().toLowerCase();
    const out = new Set<number>();
    data.nodes.forEach((n) => {
      const inActive = isActive(n);
      if (!inActive && !showArchive) return;
      if (wfFilter.size > 0 && !wfFilter.has(n.workflow)) return;
      if (milestone !== '__all__' && (n.milestone || null) !== (milestone === '__none__' ? null : milestone)) return;
      if (area !== '__all__' && n.area !== area) return;
      if (q) {
        const hay = (n.title || '').toLowerCase() + ' #' + n.number;
        if (!hay.includes(q)) return;
      }
      out.add(n.number);
    });
    return out;
  }, [data, query, wfFilter, milestone, area, showArchive]);

  const stats = useMemo(() => {
    if (!data) return null;
    const open = data.nodes.filter((n) => n.state === 'open').length;
    const active = data.nodes.filter(isActive).length;
    const closed = data.nodes.length - open;
    return { total: data.nodes.length, open, closed, active, frontier: data.frontier_count, shown: visibleNumbers.size };
  }, [data, visibleNumbers]);

  if (error) {
    return (
      <div className="atlas-empty">
        <h2>No graph data yet</h2>
        <p>{error}</p>
        <p>
          <a href="/docs/atlas-status/">See the text status page instead</a>
        </p>
      </div>
    );
  }

  if (!data || !stats) {
    return <div className="atlas-loading">Loading the Atlas graph…</div>;
  }

  const workflows = ACTIVE_WORKFLOWS.concat(['done', 'none']);
  const milestones = data.milestones.slice().sort();
  const areas = Array.from(new Set(data.nodes.map((n) => n.area))).sort();

  const toggleWf = (w: string) => {
    setWfFilter((prev) => {
      const next = new Set(prev);
      if (next.has(w)) next.delete(w);
      else next.add(w);
      return next;
    });
  };

  return (
    <div className="atlas-app">
      <div className="atlas-controls">
        <div className="atlas-stats">
          {stats.shown > 0 && (
            <span>
              <b>{stats.shown}</b> shown
            </span>
          )}
          <span>
            <b>{stats.active}</b> active
          </span>
          <span>
            <b>{stats.open}</b> open
          </span>
          <span>
            <b>{stats.frontier}</b> frontier
          </span>
          <span>
            <b>{stats.total}</b> total
          </span>
        </div>

        <label className="atlas-search">
          <span className="visually-hidden">Search issues</span>
          <input
            ref={searchBox}
            type="search"
            placeholder="Search number or title…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        <label className="atlas-toggle">
          <input type="checkbox" checked={showArchive} onChange={(e) => setShowArchive(e.target.checked)} />
          Show archive ({stats.closed} closed)
        </label>

        <label className="atlas-select">
          <span>Milestone</span>
          <select value={milestone} onChange={(e) => setMilestone(e.target.value)}>
            <option value="__all__">All milestones</option>
            <option value="__none__">No milestone</option>
            {milestones.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>

        <label className="atlas-select">
          <span>Area</span>
          <select value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="__all__">All areas</option>
            {areas.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>

        <div className="atlas-legend" role="group" aria-label="Workflow filter">
          {workflows.map((w) => (
            <button
              key={w}
              type="button"
              className={'chip' + (wfFilter.has(w) ? ' on' : '')}
              style={{ '--chip': WF_COLOR[w] } as React.CSSProperties}
              onClick={() => toggleWf(w)}
              aria-pressed={wfFilter.has(w)}
            >
              {WF_LABEL[w]}
            </button>
          ))}
        </div>
      </div>

      <div className="atlas-canvas-wrap">
        {stats.shown === 0 ? (
          <div className="atlas-empty">
            <h2>Nothing matches</h2>
            <p>
              No issue matches the current search and filters. Widen the filters, clear the search, or enable
              &ldquo;Show archive&rdquo;.
            </p>
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setWfFilter(new Set());
                setMilestone('__all__');
                setArea('__all__');
                if (searchBox.current) searchBox.current.value = '';
              }}
            >
              Reset filters
            </button>
          </div>
        ) : (
          <div className="atlas-canvas">
            <ReactFlowProvider>
              <Flow data={data} visibleNumbers={visibleNumbers} />
            </ReactFlowProvider>
          </div>
        )}
      </div>

      <div className="atlas-sync">Synced: {data.sync_time || 'unknown'} · drift: {data.drift_count}</div>
    </div>
  );
}
