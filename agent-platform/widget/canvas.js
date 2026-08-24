// Free-form widget canvas: host-side drag/resize/visibility layout for
// index.html's Canvas view mode (issue #362). Position/size state lives only
// here, in localStorage -- widget_contract/ and widget specs are untouched.
(function (global) {
  "use strict";

  var STORAGE_KEY = "cortxt-canvas-layout";
  var SNAP_PX = 8;
  var MIN_W = 220;
  var MIN_H = 160;
  var DEFAULT_W = 340;
  var DEFAULT_H = 320;
  var GAP = 14;

  function loadLayout() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function saveLayout(layout) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch (e) {}
  }

  function validEntry(entry) {
    return (
      entry &&
      typeof entry.x === "number" &&
      typeof entry.y === "number" &&
      typeof entry.w === "number" &&
      typeof entry.h === "number"
    );
  }

  // Packs widgets left-to-right, top-to-bottom into a grid equivalent to the
  // retired CSS auto-fit grid, for widgets with no saved position yet.
  function defaultRect(index, containerWidth) {
    var cols = Math.max(1, Math.floor((containerWidth + GAP) / (DEFAULT_W + GAP)));
    var col = index % cols;
    var row = Math.floor(index / cols);
    return {
      x: GAP + col * (DEFAULT_W + GAP),
      y: GAP + row * (DEFAULT_H + GAP),
      w: DEFAULT_W,
      h: DEFAULT_H,
    };
  }

  function CanvasController(container, toolbarHost) {
    this.container = container;
    this.toolbarHost = toolbarHost;
    this.layout = loadLayout();
    this.windows = {}; // widget id -> { el, header, body, resizeHandle }
    this.pickerOpen = false;
  }

  CanvasController.prototype.rectFor = function (id, index) {
    var entry = this.layout[id];
    var containerWidth = this.container.clientWidth || 1200;
    var fallback = defaultRect(index, containerWidth);
    if (!validEntry(entry)) return fallback;
    return {
      x: entry.x,
      y: entry.y,
      w: Math.max(MIN_W, entry.w),
      h: Math.max(MIN_H, entry.h),
    };
  };

  CanvasController.prototype.isVisible = function (id) {
    var entry = this.layout[id];
    return !entry || entry.visible !== false;
  };

  CanvasController.prototype.persistRect = function (id, rect) {
    var entry = this.layout[id] || {};
    entry.x = rect.x;
    entry.y = rect.y;
    entry.w = rect.w;
    entry.h = rect.h;
    if (entry.visible === undefined) entry.visible = true;
    this.layout[id] = entry;
    saveLayout(this.layout);
  };

  CanvasController.prototype.setVisible = function (id, visible) {
    var entry = this.layout[id] || {};
    entry.visible = visible;
    this.layout[id] = entry;
    saveLayout(this.layout);
  };

  CanvasController.prototype.reset = function () {
    this.layout = {};
    saveLayout(this.layout);
  };

  // Builds one draggable/resizable window per manifest widget. cardBuilder(w)
  // must return { head, root } DOM nodes (head becomes the drag handle, root
  // is where the caller renders/polls the widget's content).
  CanvasController.prototype.render = function (manifest, cardBuilder) {
    var self = this;
    this._lastCardBuilder = cardBuilder;
    this.container.replaceChildren();
    this.windows = {};
    manifest.forEach(function (w, index) {
      var rect = self.rectFor(w.id, index);
      var visible = self.isVisible(w.id);

      var win = document.createElement("div");
      win.className = "canvas-win";
      win.style.left = rect.x + "px";
      win.style.top = rect.y + "px";
      win.style.width = rect.w + "px";
      win.style.height = rect.h + "px";
      win.classList.toggle("hidden", !visible);

      var built = cardBuilder(w);
      win.append(built.head, built.root);

      var handle = document.createElement("div");
      handle.className = "canvas-resize";
      win.append(handle);

      self.container.append(win);
      self.windows[w.id] = { el: win, head: built.head };

      self.attachDrag(w.id, win, built.head);
      self.attachResize(w.id, win, handle);

      if (!self.layout[w.id]) self.persistRect(w.id, rect);
    });
    this.renderPicker(manifest);
  };

  CanvasController.prototype.attachDrag = function (id, win, handle) {
    var self = this;
    var dragging = null;
    handle.style.cursor = "grab";
    handle.addEventListener("pointerdown", function (ev) {
      if (ev.target.closest("button,input,a")) return;
      dragging = {
        startX: ev.clientX,
        startY: ev.clientY,
        origX: win.offsetLeft,
        origY: win.offsetTop,
      };
      handle.setPointerCapture(ev.pointerId);
      handle.style.cursor = "grabbing";
    });
    handle.addEventListener("pointermove", function (ev) {
      if (!dragging) return;
      var dx = ev.clientX - dragging.startX;
      var dy = ev.clientY - dragging.startY;
      var x = Math.max(0, dragging.origX + dx);
      var y = Math.max(0, dragging.origY + dy);
      win.style.left = x + "px";
      win.style.top = y + "px";
    });
    function endDrag(ev) {
      if (!dragging) return;
      dragging = null;
      handle.style.cursor = "grab";
      self.persistRect(id, {
        x: win.offsetLeft,
        y: win.offsetTop,
        w: win.offsetWidth,
        h: win.offsetHeight,
      });
    }
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  };

  // Finds the nearest touching neighbor along one axis at drag start, so a
  // corner-resize can move a shared edge together with this window. This is
  // a per-drag geometry check only -- no relationship is stored afterward.
  function findRightNeighbor(id, rect, windows) {
    var best = null;
    Object.keys(windows).forEach(function (otherId) {
      if (otherId === id) return;
      var el = windows[otherId].el;
      if (el.classList.contains("hidden")) return;
      var ox = el.offsetLeft, oy = el.offsetTop, oh = el.offsetHeight;
      var touchesRight = Math.abs(ox - (rect.x + rect.w)) <= SNAP_PX;
      var overlapsY = oy < rect.y + rect.h && oy + oh > rect.y;
      if (touchesRight && overlapsY) best = otherId;
    });
    return best;
  }

  function findBottomNeighbor(id, rect, windows) {
    var best = null;
    Object.keys(windows).forEach(function (otherId) {
      if (otherId === id) return;
      var el = windows[otherId].el;
      if (el.classList.contains("hidden")) return;
      var ox = el.offsetLeft, oy = el.offsetTop, ow = el.offsetWidth;
      var touchesBottom = Math.abs(oy - (rect.y + rect.h)) <= SNAP_PX;
      var overlapsX = ox < rect.x + rect.w && ox + ow > rect.x;
      if (touchesBottom && overlapsX) best = otherId;
    });
    return best;
  }

  CanvasController.prototype.attachResize = function (id, win, handle) {
    var self = this;
    var drag = null;
    handle.addEventListener("pointerdown", function (ev) {
      var rect = { x: win.offsetLeft, y: win.offsetTop, w: win.offsetWidth, h: win.offsetHeight };
      var rightId = findRightNeighbor(id, rect, self.windows);
      var bottomId = findBottomNeighbor(id, rect, self.windows);
      drag = {
        startX: ev.clientX,
        startY: ev.clientY,
        startW: rect.w,
        startH: rect.h,
        rightId: rightId,
        rightStart: rightId ? { x: self.windows[rightId].el.offsetLeft, w: self.windows[rightId].el.offsetWidth } : null,
        bottomId: bottomId,
        bottomStart: bottomId ? { y: self.windows[bottomId].el.offsetTop, h: self.windows[bottomId].el.offsetHeight } : null,
      };
      handle.setPointerCapture(ev.pointerId);
      ev.stopPropagation();
    });
    handle.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      var dx = ev.clientX - drag.startX;
      var dy = ev.clientY - drag.startY;
      var newW = Math.max(MIN_W, drag.startW + dx);
      var newH = Math.max(MIN_H, drag.startH + dy);
      win.style.width = newW + "px";
      win.style.height = newH + "px";

      if (drag.rightId) {
        var rightWin = self.windows[drag.rightId].el;
        var newRightX = win.offsetLeft + newW;
        var newRightW = Math.max(MIN_W, drag.rightStart.x + drag.rightStart.w - newRightX);
        rightWin.style.left = newRightX + "px";
        rightWin.style.width = newRightW + "px";
      }
      if (drag.bottomId) {
        var bottomWin = self.windows[drag.bottomId].el;
        var newBottomY = win.offsetTop + newH;
        var newBottomH = Math.max(MIN_H, drag.bottomStart.y + drag.bottomStart.h - newBottomY);
        bottomWin.style.top = newBottomY + "px";
        bottomWin.style.height = newBottomH + "px";
      }
    });
    function endResize(ev) {
      if (!drag) return;
      self.persistRect(id, { x: win.offsetLeft, y: win.offsetTop, w: win.offsetWidth, h: win.offsetHeight });
      if (drag.rightId) {
        var rw = self.windows[drag.rightId].el;
        self.persistRect(drag.rightId, { x: rw.offsetLeft, y: rw.offsetTop, w: rw.offsetWidth, h: rw.offsetHeight });
      }
      if (drag.bottomId) {
        var bw = self.windows[drag.bottomId].el;
        self.persistRect(drag.bottomId, { x: bw.offsetLeft, y: bw.offsetTop, w: bw.offsetWidth, h: bw.offsetHeight });
      }
      drag = null;
    }
    handle.addEventListener("pointerup", endResize);
    handle.addEventListener("pointercancel", endResize);
  };

  CanvasController.prototype.renderPicker = function (manifest) {
    var self = this;
    if (!this.toolbarHost) return;
    this.toolbarHost.replaceChildren();

    var addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "canvas-tool-btn";
    addBtn.textContent = "+ Widgets";
    var panel = document.createElement("div");
    panel.className = "canvas-picker hidden";
    manifest.forEach(function (w) {
      var row = document.createElement("label");
      row.className = "canvas-picker-row";
      var box = document.createElement("input");
      box.type = "checkbox";
      box.checked = self.isVisible(w.id);
      box.onchange = function () {
        self.setVisible(w.id, box.checked);
        var win = self.windows[w.id];
        if (win) win.el.classList.toggle("hidden", !box.checked);
      };
      var label = document.createElement("span");
      label.textContent = w.title || w.id;
      row.append(box, label);
      panel.append(row);
    });
    addBtn.onclick = function () {
      self.pickerOpen = !self.pickerOpen;
      panel.classList.toggle("hidden", !self.pickerOpen);
    };

    var resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.className = "canvas-tool-btn";
    resetBtn.textContent = "Reset layout";
    resetBtn.onclick = function () {
      self.reset();
      self.render(manifest, self._lastCardBuilder);
    };

    this.toolbarHost.append(addBtn, resetBtn, panel);
  };

  global.CortxtCanvas = { CanvasController: CanvasController };
})(window);
