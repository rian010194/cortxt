// Split/docking-tree layout for index.html's Canvas view mode (issue #369).
// Replaces canvas.js's free-position model: the tree always fills its
// container exactly, so there is never a scrollbar and widgets can never
// leave the visible area. Written container-agnostic (constructed with a
// target element + a widget list) so a future multi-window issue can
// instantiate one DockTree per window without rewriting this module.
(function (global) {
  "use strict";

  var STORAGE_KEY = "cortxt-dock-layout";
  var EDGE_ZONE = 0.2; // fraction of a leaf's size that counts as an edge drop
  var MIN_FRACTION = 0.12;
  var DIVIDER_PX = 6;

  function uid() {
    return "n" + Math.random().toString(36).slice(2, 10);
  }

  function leaf(tabs, active) {
    return { type: "leaf", id: uid(), tabs: tabs.slice(), active: active || 0 };
  }

  function split(dir, children, sizes) {
    return { type: "split", id: uid(), dir: dir, children: children, sizes: sizes };
  }

  // Balanced binary split tree, alternating row/column at each level, as a
  // reasonable first-load arrangement -- roughly grid-like without being a
  // rigid grid.
  function buildBalanced(ids, dir) {
    if (ids.length === 1) return leaf([ids[0]]);
    var mid = Math.ceil(ids.length / 2);
    var left = ids.slice(0, mid);
    var right = ids.slice(mid);
    var nextDir = dir === "row" ? "column" : "row";
    return split(dir, [buildBalanced(left, nextDir), buildBalanced(right, nextDir)], [left.length / ids.length, right.length / ids.length]);
  }

  function defaultTree(widgetIds) {
    if (!widgetIds.length) return leaf([]);
    return buildBalanced(widgetIds, "row");
  }

  function findLeafById(node, id) {
    if (node.type === "leaf") return node.id === id ? node : null;
    for (var i = 0; i < node.children.length; i++) {
      var found = findLeafById(node.children[i], id);
      if (found) return found;
    }
    return null;
  }

  // Removes a widget tab from wherever it lives in the tree. Collapses an
  // emptied leaf, and a split reduced to one child collapses into that
  // child, so the tree never accumulates dead nodes.
  function removeTab(node, widgetId) {
    if (node.type === "leaf") {
      var idx = node.tabs.indexOf(widgetId);
      if (idx === -1) return node;
      var tabs = node.tabs.slice();
      tabs.splice(idx, 1);
      if (!tabs.length) return null;
      return leaf(tabs, Math.min(node.active, tabs.length - 1));
    }
    var children = [];
    var sizes = [];
    for (var i = 0; i < node.children.length; i++) {
      var child = removeTab(node.children[i], widgetId);
      if (child) {
        children.push(child);
        sizes.push(node.sizes[i]);
      }
    }
    if (!children.length) return null;
    if (children.length === 1) return children[0];
    var total = sizes.reduce(function (a, b) { return a + b; }, 0) || 1;
    sizes = sizes.map(function (s) { return s / total; });
    return split(node.dir, children, sizes);
  }

  function collectWidgetIds(node, out) {
    out = out || [];
    if (node.type === "leaf") {
      node.tabs.forEach(function (id) { out.push(id); });
    } else {
      node.children.forEach(function (c) { collectWidgetIds(c, out); });
    }
    return out;
  }

  function replaceLeaf(node, leafId, replacement) {
    if (node.type === "leaf") {
      return node.id === leafId ? replacement : node;
    }
    var children = node.children.map(function (c) { return replaceLeaf(c, leafId, replacement); });
    return split(node.dir, children, node.sizes.slice());
  }

  function validTree(node) {
    if (!node || typeof node !== "object") return false;
    if (node.type === "leaf") return Array.isArray(node.tabs);
    if (node.type === "split") {
      return (
        (node.dir === "row" || node.dir === "column") &&
        Array.isArray(node.children) &&
        Array.isArray(node.sizes) &&
        node.children.length === node.sizes.length &&
        node.children.every(validTree)
      );
    }
    return false;
  }

  function loadStoredState() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || !validTree(parsed.tree)) return null;
      return { tree: parsed.tree, hidden: Array.isArray(parsed.hidden) ? parsed.hidden : [] };
    } catch (e) {
      return null;
    }
  }

  function saveState(tree, hidden) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ tree: tree, hidden: hidden }));
    } catch (e) {}
  }

  function DockTree(container, manifest, cardBuilder) {
    this.container = container;
    this.manifest = manifest;
    this.cardBuilder = cardBuilder;
    this.byId = {};
    manifest.forEach((w) => { this.byId[w.id] = w; });
    var stored = loadStoredState();
    var known = Object.keys(this.byId);
    this.hidden = stored ? stored.hidden.filter((id) => known.indexOf(id) !== -1) : [];
    this.tree = this._reconcile(stored ? stored.tree : null) || defaultTree(manifest.map((w) => w.id));
    this._persist();
  }

  // Drops unknown widget ids, appends any widget missing from the tree
  // (unless it was deliberately hidden via the picker).
  DockTree.prototype._reconcile = function (tree) {
    if (!tree) return null;
    var known = Object.keys(this.byId);
    var present = collectWidgetIds(tree);
    var pruned = tree;
    present.forEach((id) => {
      if (known.indexOf(id) === -1) pruned = removeTab(pruned, id) || pruned;
    });
    if (!pruned) return null;
    var stillPresent = collectWidgetIds(pruned);
    var missing = known.filter((id) => stillPresent.indexOf(id) === -1 && this.hidden.indexOf(id) === -1);
    if (missing.length) {
      var target = this._firstLeaf(pruned);
      if (target) {
        var merged = leaf(target.tabs.concat(missing), target.active);
        pruned = replaceLeaf(pruned, target.id, merged);
      } else {
        pruned = defaultTree(missing);
      }
    }
    return pruned;
  };

  DockTree.prototype._firstLeaf = function (node) {
    if (!node) return null;
    if (node.type === "leaf") return node;
    for (var i = 0; i < node.children.length; i++) {
      var f = this._firstLeaf(node.children[i]);
      if (f) return f;
    }
    return null;
  };

  DockTree.prototype.reset = function () {
    this.hidden = [];
    this.tree = defaultTree(this.manifest.map((w) => w.id));
    this._persist();
    this.render();
  };

  DockTree.prototype._persist = function () {
    saveState(this.tree, this.hidden);
  };

  DockTree.prototype.isVisible = function (widgetId) {
    return this.hidden.indexOf(widgetId) === -1;
  };

  DockTree.prototype.hideWidget = function (widgetId) {
    if (this.hidden.indexOf(widgetId) === -1) this.hidden.push(widgetId);
    this.tree = removeTab(this.tree, widgetId) || defaultTree([]);
    this._persist();
    this.render();
  };

  DockTree.prototype.showWidget = function (widgetId) {
    this.hidden = this.hidden.filter((id) => id !== widgetId);
    var target = this._firstLeaf(this.tree);
    if (target) {
      var merged = leaf(target.tabs.concat(widgetId), target.tabs.length);
      this.tree = replaceLeaf(this.tree, target.id, merged);
    } else {
      this.tree = leaf([widgetId]);
    }
    this._persist();
    this.render();
  };

  DockTree.prototype.render = function () {
    this.container.replaceChildren();
    this.container.append(this._renderNode(this.tree));
    if (typeof this.onRender === "function") this.onRender();
  };

  DockTree.prototype._renderNode = function (node) {
    if (node.type === "leaf") return this._renderLeaf(node);
    var box = document.createElement("div");
    box.className = "dock-split dock-" + node.dir;
    node.children.forEach((child, i) => {
      var pane = document.createElement("div");
      pane.className = "dock-pane";
      pane.style.flex = node.sizes[i] + " " + node.sizes[i] + " 0";
      pane.append(this._renderNode(child));
      box.append(pane);
      if (i < node.children.length - 1) {
        box.append(this._buildDivider(node, i));
      }
    });
    return box;
  };

  DockTree.prototype._buildDivider = function (splitNode, index) {
    var self = this;
    var div = document.createElement("div");
    div.className = "dock-divider dock-divider-" + splitNode.dir;
    var drag = null;
    div.addEventListener("pointerdown", (ev) => {
      var box = div.parentElement;
      var rect = box.getBoundingClientRect();
      drag = {
        start: splitNode.dir === "row" ? ev.clientX : ev.clientY,
        total: splitNode.dir === "row" ? rect.width : rect.height,
        sizesBefore: splitNode.sizes.slice(),
      };
      div.setPointerCapture(ev.pointerId);
    });
    div.addEventListener("pointermove", (ev) => {
      if (!drag) return;
      var pos = splitNode.dir === "row" ? ev.clientX : ev.clientY;
      var delta = (pos - drag.start) / drag.total;
      var a = Math.max(MIN_FRACTION, drag.sizesBefore[index] + delta);
      var b = Math.max(MIN_FRACTION, drag.sizesBefore[index + 1] - delta);
      var sum = drag.sizesBefore[index] + drag.sizesBefore[index + 1];
      if (a + b > sum) {
        var over = a + b - sum;
        if (a > b) a -= over; else b -= over;
      }
      splitNode.sizes[index] = a;
      splitNode.sizes[index + 1] = b;
      self.render();
    });
    function end() {
      if (!drag) return;
      drag = null;
      self._persist();
    }
    div.addEventListener("pointerup", end);
    div.addEventListener("pointercancel", end);
    return div;
  };

  DockTree.prototype._renderLeaf = function (node) {
    var self = this;
    var wrap = document.createElement("div");
    wrap.className = "dock-leaf";

    var tabbar = document.createElement("div");
    tabbar.className = "dock-tabbar";
    var body = document.createElement("div");
    body.className = "dock-body";

    node.tabs.forEach((widgetId, i) => {
      var w = self.byId[widgetId];
      if (!w) return;
      var tab = document.createElement("div");
      tab.className = "dock-tab" + (i === node.active ? " active" : "");
      tab.textContent = w.title || w.id;
      tab.draggable = true;
      tab.dataset.widgetId = widgetId;
      tab.onclick = () => {
        node.active = i;
        self._persist();
        self.render();
      };
      var close = document.createElement("span");
      close.className = "dock-tab-close";
      close.textContent = "×";
      close.onclick = (ev) => {
        ev.stopPropagation();
        self.hideWidget(widgetId);
      };
      tab.append(close);
      self._attachTabDrag(tab, widgetId);
      tabbar.append(tab);
    });

    var activeWidget = self.byId[node.tabs[node.active]];
    if (activeWidget) {
      var built = self.cardBuilder(activeWidget);
      body.append(built.head, built.root);
    }

    self._attachDropZones(wrap, node);
    wrap.append(tabbar, body);
    return wrap;
  };

  DockTree.prototype._attachTabDrag = function (tabEl, widgetId) {
    tabEl.addEventListener("dragstart", (ev) => {
      ev.dataTransfer.setData("text/cortxt-widget-id", widgetId);
      ev.dataTransfer.effectAllowed = "move";
    });
  };

  DockTree.prototype._attachDropZones = function (leafEl, node) {
    var self = this;
    var overlay = document.createElement("div");
    overlay.className = "dock-drop-overlay hidden";
    ["top", "bottom", "left", "right", "center"].forEach((zone) => {
      var z = document.createElement("div");
      z.className = "dock-drop-zone dock-drop-" + zone;
      overlay.append(z);
    });
    leafEl.append(overlay);

    leafEl.addEventListener("dragover", (ev) => {
      if (!ev.dataTransfer.types.includes("text/cortxt-widget-id")) return;
      ev.preventDefault();
      overlay.classList.remove("hidden");
      var rect = leafEl.getBoundingClientRect();
      var x = (ev.clientX - rect.left) / rect.width;
      var y = (ev.clientY - rect.top) / rect.height;
      var zone = self._zoneFor(x, y);
      overlay.querySelectorAll(".dock-drop-zone").forEach((z) => z.classList.remove("active"));
      overlay.querySelector(".dock-drop-" + zone)?.classList.add("active");
      overlay.dataset.zone = zone;
    });
    leafEl.addEventListener("dragleave", (ev) => {
      if (ev.target === leafEl) overlay.classList.add("hidden");
    });
    leafEl.addEventListener("drop", (ev) => {
      ev.preventDefault();
      overlay.classList.add("hidden");
      var widgetId = ev.dataTransfer.getData("text/cortxt-widget-id");
      if (!widgetId || !self.byId[widgetId]) return;
      var zone = overlay.dataset.zone || "center";
      self._handleDrop(node.id, widgetId, zone);
    });
  };

  DockTree.prototype._zoneFor = function (x, y) {
    if (y < EDGE_ZONE) return "top";
    if (y > 1 - EDGE_ZONE) return "bottom";
    if (x < EDGE_ZONE) return "left";
    if (x > 1 - EDGE_ZONE) return "right";
    return "center";
  };

  DockTree.prototype._handleDrop = function (targetLeafId, widgetId, zone) {
    var targetLeaf = findLeafById(this.tree, targetLeafId);
    if (!targetLeaf || targetLeaf.tabs.indexOf(widgetId) !== -1) return;

    var withoutSource = removeTab(this.tree, widgetId);
    var currentTarget = withoutSource ? findLeafById(withoutSource, targetLeafId) : null;
    if (!currentTarget) {
      // The drag source WAS the target leaf's only content -- nothing to do.
      return;
    }
    var base = withoutSource;

    if (zone === "center") {
      var merged = leaf(currentTarget.tabs.concat(widgetId), currentTarget.tabs.length);
      this.tree = replaceLeaf(base, targetLeafId, merged);
    } else {
      var dir = zone === "left" || zone === "right" ? "row" : "column";
      var newLeaf = leaf([widgetId]);
      var children = zone === "left" || zone === "top" ? [newLeaf, currentTarget] : [currentTarget, newLeaf];
      var replacement = split(dir, children, [0.5, 0.5]);
      this.tree = replaceLeaf(base, targetLeafId, replacement);
    }
    this._persist();
    this.render();
  };

  global.CortxtDock = { DockTree: DockTree, defaultTree: defaultTree };
})(window);
