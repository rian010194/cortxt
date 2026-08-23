/* Visual Atlas renderer (issue #300): static, self-contained, no external
   dependencies. Fetches ./graph.json (emitted by scripts/atlas_sync.py),
   lays out issues as nodes grouped by milestone, draws blocked_by / part_of
   edges as SVG links, highlights the actionable frontier, and supports hover
   tooltips plus click-through to the GitHub issue.
   Content-free: never emits issue bodies, prompts, or reasoning. */
(function () {
  'use strict';

  var GRAPH_URL = './graph.json';
  var REPO = 'rian010194/cortxt';
  var NODE_W = 260;
  var NODE_H = 54;
  var GAP_X = 70;
  var GAP_Y = 26;
  var PAD = 40;

  var WF_LABEL = {
    'inbox': 'inbox',
    'ready': 'ready',
    'in-progress': 'in progress',
    'review': 'review',
    'blocked': 'blocked',
    'done': 'done',
    'none': 'no label'
  };
  var WF_COLOR = {
    'inbox': '#d4c5f9',
    'ready': '#3fb950',
    'in-progress': '#d29922',
    'review': '#1d76db',
    'blocked': '#f85149',
    'done': '#56617a',
    'none': '#8792a8'
  };
  var WF_ORDER = ['ready', 'in-progress', 'review', 'blocked', 'inbox', 'done', 'none'];

  var graphEl = document.getElementById('atlas-graph');
  var emptyEl = document.getElementById('atlas-empty');
  var controlsEl = document.getElementById('atlas-controls');
  var statsEl = document.getElementById('atlas-stats');
  var legendEl = document.getElementById('atlas-legend');
  var syncEl = document.getElementById('atlas-sync');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function truncatedTitle(t, n) {
    var s = String(t || ('#' + n));
    return s.length > 44 ? s.slice(0, 43) + '\u2026' : s;
  }

  function buildLegend() {
    var html = '';
    Object.keys(WF_COLOR).forEach(function (k) {
      html += '<span class="lg"><span class="sw" style="background:' + WF_COLOR[k] + '"></span>' +
        esc(WF_LABEL[k]) + '</span>';
    });
    html += '<span class="lg"><span class="sw" style="background:transparent;border:2px solid #4d6bfe"></span>frontier</span>';
    html += '<span class="lg"><span style="color:#ff5c5c">\u2014\u2014</span> blocked by</span>';
    html += '<span class="lg"><span style="color:#7c8fff">\u2014</span> part of</span>';
    legendEl.innerHTML = html;
  }

  function layout(g) {
    /* Group nodes by milestone; within a column order by WF_ORDER then number. */
    var byMilestone = {};
    g.nodes.forEach(function (node) {
      var key = node.milestone || 'No milestone';
      (byMilestone[key] = byMilestone[key] || []).push(node);
    });
    var columns = [];
    Object.keys(byMilestone).sort().forEach(function (key) {
      var nodes = byMilestone[key].slice().sort(function (a, b) {
        var d = (WF_ORDER.indexOf(a.workflow) - WF_ORDER.indexOf(b.workflow));
        return d !== 0 ? d : (a.number - b.number);
      });
      columns.push({ key: key, nodes: nodes });
    });
    return columns;
  }

  function positions(columns) {
    /* Assign node (x,y) centers. Return map number -> {x,y}. */
    var pos = {};
    var x = PAD;
    var maxH = 0;
    columns.forEach(function (col) {
      var y = PAD + 40; // room for the milestone label
      col.nodes.forEach(function (node) {
        pos[node.number] = { x: x, y: y, cx: x + NODE_W / 2, cy: y + NODE_H / 2 };
        y += NODE_H + GAP_Y;
      });
      var colH = y - GAP_Y + PAD;
      if (colH > maxH) maxH = colH;
      x += NODE_W + GAP_X;
    });
    return { pos: pos, width: x - GAP_X + PAD, height: maxH };
  }

  function nodeById(g) {
    var m = {};
    g.nodes.forEach(function (n) { m[n.number] = n; });
    return m;
  }

  function render(g) {
    var cols = layout(g);
    var laid = positions(cols);
    var byId = nodeById(g);

    var W = Math.max(laid.width, 720);
    var H = Math.max(laid.height, 200);

    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Atlas roadmap graph');

    // Edges first (under nodes).
    g.edges.forEach(function (edge) {
      var from = laid.pos[edge.from];
      var to = laid.pos[edge.to];
      if (!from || !to) return;
      var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('class', 'edge ' + edge.kind);
      line.setAttribute('x1', from.cx);
      line.setAttribute('y1', from.cy);
      line.setAttribute('x2', to.cx);
      line.setAttribute('y2', to.cy);
      svg.appendChild(line);
      // arrowhead marker
      var marker = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      marker.setAttribute('class', 'edge-mark');
      marker.setAttribute('d', 'M ' + (to.cx - 7) + ' ' + (to.cy - 4) + ' L ' + to.cx + ' ' + to.cy +
        ' L ' + (to.cx - 7) + ' ' + (to.cy + 4));
      marker.setAttribute('stroke', edge.kind === 'blocked_by' ? '#ff5c5c' : '#7c8fff');
      marker.setAttribute('stroke-width', '1.4');
      marker.setAttribute('fill', 'none');
      svg.appendChild(marker);
    });

    // Milestone labels + nodes.
    var yTop = PAD;
    cols.forEach(function (col) {
      var colX = laid.pos[col.nodes[0].number].x;
      var label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      label.setAttribute('class', 'milestone-label');
      label.setAttribute('x', colX);
      label.setAttribute('y', yTop);
      label.textContent = esc(col.key).slice(0, 40);
      svg.appendChild(label);
    });

    var byNumber = {};
    g.nodes.forEach(function (node) {
      var p = laid.pos[node.number];
      if (!p) return;
      byNumber[node.number] = node;

      var gNode = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      gNode.setAttribute('class', 'node wf-' + node.workflow + (node.frontier ? ' frontier' : ''));
      gNode.setAttribute('transform', 'translate(' + p.x + ',' + p.y + ')');

      var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('width', NODE_W);
      rect.setAttribute('height', NODE_H);
      rect.setAttribute('rx', 8);
      rect.setAttribute('ry', 8);

      var t1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t1.setAttribute('x', 10);
      t1.setAttribute('y', 20);
      t1.setAttribute('class', 'ghost');
      t1.textContent = truncatedTitle(node.title, node.number);

      var t1b = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t1b.setAttribute('x', 10);
      t1b.setAttribute('y', 20);
      t1b.textContent = truncatedTitle(node.title, node.number);

      var t2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      t2.setAttribute('x', 10);
      t2.setAttribute('y', 36);
      t2.setAttribute('fill', '#aab3c5');
      t2.setAttribute('font-size', '10px');
      t2.textContent = '#' + node.number + ' \u00b7 ' + (WF_LABEL[node.workflow] || node.workflow) +
        (node.state === 'closed' ? ' \u00b7 closed' : '') +
        (node.work_kind && node.work_kind !== 'delivery' ? ' \u00b7 ' + node.work_kind : '');

      // tooltip (HTML positioned in the wrapper via absolute positioning)
      var tip = document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');
      tip.setAttribute('x', -4);
      tip.setAttribute('y', NODE_H + 6);
      tip.setAttribute('width', NODE_W + 8);
      tip.setAttribute('height', 90);
      var tipDiv = document.createElement('div');
      tipDiv.className = 'tooltip';
      tipDiv.innerHTML =
        '<b>' + esc(node.title) + '</b><br/><span class="muted">#' + node.number +
        ' \u00b7 ' + esc(WF_LABEL[node.workflow] || node.workflow) +
        (node.state === 'closed' ? ' \u00b7 closed' : '') +
        (node.milestone ? ' \u00b7 ' + esc(node.milestone) : '') +
        (node.area && node.area !== 'Other' ? ' \u00b7 ' + esc(node.area) : '') +
        '</span>';
      tip.appendChild(tipDiv);

      gNode.appendChild(rect);
      gNode.appendChild(t1);
      gNode.appendChild(t1b);
      gNode.appendChild(t2);
      gNode.appendChild(tip);

      // click through
      gNode.addEventListener('click', function () {
        window.open('https://github.com/' + REPO + '/issues/' + node.number, '_blank');
      });

      svg.appendChild(gNode);
    });

    graphEl.appendChild(svg);
  }

  function renderStats(g) {
    var open = g.nodes.filter(function (n) { return n.state === 'open'; }).length;
    var closed = g.nodes.length - open;
    statsEl.innerHTML =
      '<span><b>' + g.nodes.length + '</b> issues</span>' +
      '<span><b>' + g.milestones.length + '</b> milestones</span>' +
      '<span><b>' + g.frontier_count + '</b> frontier</span>' +
      '<span><b>' + open + '</b> open</span>' +
      '<span><b>' + closed + '</b> closed</span>';
  }

  function renderSync(g) {
    syncEl.textContent = 'Synced: ' + (g.sync_time || 'unknown');
  }

  function failEmpty(msg) {
    graphEl.hidden = true;
    controlsEl.hidden = true;
    emptyEl.hidden = false;
    emptyEl.querySelector('p').textContent = msg || emptyEl.querySelector('p').textContent;
  }

  function load() {
    buildLegend();
    fetch(GRAPH_URL, { headers: { 'Accept': 'application/json' } })
      .then(function (resp) {
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return resp.json();
      })
      .then(function (g) {
        if (!g || !Array.isArray(g.nodes) || g.nodes.length === 0) {
          failEmpty('The graph file exists but contains no nodes yet. It will populate after the next Atlas sync.');
          return;
        }
        render(g);
        renderStats(g);
        renderSync(g);
        controlsEl.hidden = false;
      })
      .catch(function (err) {
        failEmpty('Could not load the Atlas graph (' + (err && err.message ? err.message : 'network error') +
          '). It is generated by the daily Atlas sync; check back after the next sync, or see the text status page.');
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
