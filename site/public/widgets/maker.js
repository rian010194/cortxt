/**
 * Cortxt Widget Maker - Shared Client-Side Renderer
 * Mirroring widget_contract/renderer.py and registry primitives.
 * Pure JavaScript, zero external dependencies.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.WidgetMaker = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /**
   * RFC 6901 JSON Pointer resolver.
   */
  function resolvePointer(doc, pointer) {
    if (doc === undefined || doc === null) return undefined;
    if (!pointer || pointer === "") return doc;
    if (pointer.charCodeAt(0) !== 47) return undefined; // Must start with '/'

    const parts = pointer.slice(1).split("/");
    let current = doc;

    for (let i = 0; i < parts.length; i++) {
      if (current === undefined || current === null) return undefined;
      const part = parts[i].replace(/~1/g, "/").replace(/~0/g, "~");

      if (Array.isArray(current)) {
        const idx = Number(part);
        if (Number.isInteger(idx) && idx >= 0 && idx < current.length) {
          current = current[idx];
        } else {
          return undefined;
        }
      } else if (typeof current === "object") {
        if (Object.prototype.hasOwnProperty.call(current, part)) {
          current = current[part];
        } else {
          return undefined;
        }
      } else {
        return undefined;
      }
    }
    return current;
  }

  /**
   * Compact, safe YAML subset parser for widget specs.
   * Handles maps, lists, inline arrays/objects, scalars, comments.
   * Authoritative validation is always performed server-side via `cortxt widget load`.
   */
  function parseYamlSubset(yamlText) {
    if (typeof yamlText !== "string") {
      return { ok: false, error: "Input must be a string." };
    }

    function parseScalar(val) {
      val = val.trim();
      if (val === "" || val === "~" || val === "null") return null;
      if (val === "true" || val === "True" || val === "TRUE") return true;
      if (val === "false" || val === "False" || val === "FALSE") return false;

      // Quoted string
      if (
        (val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))
      ) {
        return val.slice(1, -1);
      }

      // Inline array
      if (val.startsWith("[") && val.endsWith("]")) {
        const inner = val.slice(1, -1).trim();
        if (!inner) return [];
        return splitInlineList(inner).map(parseScalar);
      }

      // Inline object
      if (val.startsWith("{") && val.endsWith("}")) {
        const inner = val.slice(1, -1).trim();
        if (!inner) return {};
        const obj = {};
        const entries = splitInlineDict(inner);
        for (const entry of entries) {
          const colonIdx = entry.indexOf(":");
          if (colonIdx !== -1) {
            const k = entry.slice(0, colonIdx).trim().replace(/^['"]|['"]$/g, "");
            const v = entry.slice(colonIdx + 1).trim();
            obj[k] = parseScalar(v);
          }
        }
        return obj;
      }

      // Number
      if (/^-?\d+(\.\d+)?$/.test(val)) {
        const num = Number(val);
        if (!Number.isNaN(num)) return num;
      }

      return val;
    }

    function splitInlineList(text) {
      const items = [];
      let current = "";
      let depth = 0;
      let quote = null;

      for (let i = 0; i < text.length; i++) {
        const c = text[i];
        if (quote) {
          current += c;
          if (c === quote && text[i - 1] !== "\\") quote = null;
        } else if (c === '"' || c === "'") {
          quote = c;
        } else if (c === "[" || c === "{") {
          depth++;
          current += c;
        } else if (c === "]" || c === "}") {
          depth--;
          current += c;
        } else if (c === "," && depth === 0) {
          items.push(current.trim());
          current = "";
        } else {
          current += c;
        }
      }
      if (current.trim()) items.push(current.trim());
      return items;
    }

    function splitInlineDict(text) {
      return splitInlineList(text);
    }

    try {
      const rawLines = yamlText.split(/\r?\n/);
      const lines = [];

      for (let idx = 0; idx < rawLines.length; idx++) {
        let line = rawLines[idx];
        // Strip trailing comments (not inside quotes)
        let inQuote = null;
        let commentIdx = -1;
        for (let j = 0; j < line.length; j++) {
          const ch = line[j];
          if (inQuote) {
            if (ch === inQuote && line[j - 1] !== "\\") inQuote = null;
          } else if (ch === '"' || ch === "'") {
            inQuote = ch;
          } else if (ch === "#") {
            commentIdx = j;
            break;
          }
        }
        if (commentIdx !== -1) {
          line = line.slice(0, commentIdx);
        }
        const trimmed = line.trimEnd();
        if (trimmed.trim().length === 0) continue; // skip blank lines

        const indent = line.search(/\S/);
        lines.push({ indent, text: trimmed.slice(indent), lineNum: idx + 1 });
      }

      if (lines.length === 0) {
        return { ok: true, data: {} };
      }

      let lineIdx = 0;

      function parseBlock(currentIndent) {
        if (lineIdx >= lines.length) return {};
        const first = lines[lineIdx];
        const isList = first.text.startsWith("- ") || first.text === "-";

        if (isList) {
          const list = [];
          while (lineIdx < lines.length) {
            const line = lines[lineIdx];
            if (line.indent < currentIndent) break;
            if (line.indent > currentIndent && !line.text.startsWith("-")) {
              break;
            }
            if (!line.text.startsWith("-")) break;

            const content = line.text.slice(1).trim();
            lineIdx++;

            if (!content) {
              // Item with nested block
              if (lineIdx < lines.length && lines[lineIdx].indent > line.indent) {
                list.push(parseBlock(lines[lineIdx].indent));
              } else {
                list.push(null);
              }
            } else if (content.includes(":") && !content.startsWith("{") && !content.startsWith("[")) {
              // List item that is a map: e.g. - id: candidates
              const mapObj = {};
              const colonIdx = content.indexOf(":");
              const k = content.slice(0, colonIdx).trim();
              const v = content.slice(colonIdx + 1).trim();

              if (!v) {
                if (lineIdx < lines.length && lines[lineIdx].indent > line.indent) {
                  mapObj[k] = parseBlock(lines[lineIdx].indent);
                } else {
                  mapObj[k] = null;
                }
              } else {
                mapObj[k] = parseScalar(v);
              }

              // Parse further keys for the same list item if indented
              while (lineIdx < lines.length) {
                const nextLine = lines[lineIdx];
                if (nextLine.indent <= line.indent || nextLine.text.startsWith("-")) {
                  break;
                }
                const subColon = nextLine.text.indexOf(":");
                if (subColon !== -1) {
                  const subKey = nextLine.text.slice(0, subColon).trim();
                  const subVal = nextLine.text.slice(subColon + 1).trim();
                  lineIdx++;
                  if (!subVal) {
                    if (lineIdx < lines.length && lines[lineIdx].indent > nextLine.indent) {
                      mapObj[subKey] = parseBlock(lines[lineIdx].indent);
                    } else {
                      mapObj[subKey] = null;
                    }
                  } else {
                    mapObj[subKey] = parseScalar(subVal);
                  }
                } else {
                  lineIdx++;
                }
              }
              list.push(mapObj);
            } else {
              list.push(parseScalar(content));
            }
          }
          return list;
        }

        const map = {};
        while (lineIdx < lines.length) {
          const line = lines[lineIdx];
          if (line.indent < currentIndent) break;

          const colonIdx = line.text.indexOf(":");
          if (colonIdx === -1) {
            lineIdx++;
            continue;
          }

          const key = line.text.slice(0, colonIdx).trim().replace(/^['"]|['"]$/g, "");
          const rawVal = line.text.slice(colonIdx + 1).trim();
          lineIdx++;

          if (!rawVal) {
            if (lineIdx < lines.length && lines[lineIdx].indent > line.indent) {
              map[key] = parseBlock(lines[lineIdx].indent);
            } else {
              map[key] = null;
            }
          } else {
            map[key] = parseScalar(rawVal);
          }
        }
        return map;
      }

      const parsed = parseBlock(lines[0].indent);
      return { ok: true, data: parsed };
    } catch (err) {
      return { ok: false, error: err.message || "Failed to parse YAML" };
    }
  }

  /**
   * Render widget spec + bound fixture data into a JSON render tree.
   * Mirrors widget_contract/renderer.py.
   */
  function renderSpec(spec, data, readStates) {
    data = data || {};
    readStates = readStates || {};

    if (!spec || typeof spec !== "object") {
      throw new Error("Invalid spec object");
    }
    if (!spec.render || typeof spec.render !== "object") {
      throw new Error("Spec must define a 'render' root node");
    }

    function renderNode(node) {
      if (!node || typeof node !== "object") return null;

      // Handle 'when' condition
      if (node.when) {
        if (typeof node.when === "object" && node.when.read) {
          const condition = resolvePointer(data[node.when.read], node.when.pointer);
          if (condition !== true) {
            return null;
          }
        }
      }

      const primitive = node.primitive || "stack";
      const props = Object.assign({}, node.props || {});
      let state = "ready";

      if (node.bindings && typeof node.bindings === "object") {
        for (const propName of Object.keys(node.bindings)) {
          const binding = node.bindings[propName];
          if (!binding || !binding.read) continue;

          const sourceData = data[binding.read];
          const sourceState = readStates[binding.read] || "ready";

          if (sourceData === undefined) {
            state = ["stale", "denied", "error"].includes(sourceState)
              ? sourceState
              : "empty";
          } else {
            const val = resolvePointer(sourceData, binding.pointer);
            if (val === undefined) {
              state = ["stale", "denied", "error"].includes(sourceState)
                ? sourceState
                : "empty";
            } else {
              props[propName] = val;
              if (["stale", "denied", "error"].includes(sourceState)) {
                state = sourceState;
              }
            }
          }
        }
      }

      const children = [];
      if (Array.isArray(node.children)) {
        for (const child of node.children) {
          const renderedChild = renderNode(child);
          if (renderedChild !== null) {
            children.push(renderedChild);
          }
        }
      }

      return {
        primitive: primitive,
        state: state,
        props: props,
        children: children,
      };
    }

    let renderedTree = renderNode(spec.render);
    if (!renderedTree) {
      renderedTree = {
        primitive: "empty-state",
        state: "empty",
        props: { message: "hidden" },
        children: [],
      };
    }

    return {
      contract_version: spec.contract_version || "0.1",
      widget: {
        id: (spec.widget && spec.widget.id) || "custom",
        version: (spec.widget && spec.widget.version) || "0.1",
      },
      render: renderedTree,
    };
  }

  /**
   * Render DOM elements for a render node into a target container.
   */
  function renderNodeToDom(node, container, options) {
    if (!node || !container) return;
    options = options || {};

    const p = node.props || {};
    const primitive = node.primitive || "stack";
    const children = node.children || [];

    // Container primitives: stack, row, grid, panel, tabs
    if (primitive === "stack" || primitive === "row" || primitive === "grid" || primitive === "panel" || primitive === "tabs") {
      const box = document.createElement("div");
      box.className = "widget-" + primitive;
      if (primitive === "panel" && p.label) {
        const title = document.createElement("div");
        title.className = "eyebrow";
        title.textContent = p.label;
        box.append(title);
      }
      children.forEach(function (child) {
        renderNodeToDom(child, box, options);
      });
      container.append(box);
      return;
    }

    // Heading, Text, Badge
    if (primitive === "heading" || primitive === "text" || primitive === "badge") {
      const el = document.createElement("div");
      const val = p.value !== undefined ? p.value : p.label !== undefined ? p.label : "";
      if (primitive === "heading") {
        el.className = "pulse-status widget-heading";
        el.innerHTML = "<strong>" + escapeHtml(String(val)) + "</strong>";
      } else if (primitive === "badge") {
        el.className = "badge" + (node.state === "error" ? " err" : node.state === "ready" ? " ok" : "");
        el.textContent = String(val);
      } else {
        el.className = "pulse-status widget-text";
        el.textContent = String(val);
      }
      container.append(el);
      return;
    }

    // Metric
    if (primitive === "metric") {
      const stat = document.createElement("div");
      stat.className = "pulse-stat";
      const b = document.createElement("b");
      b.textContent = p.value !== undefined ? String(p.value) : "-";
      const span = document.createElement("span");
      span.textContent = p.label || "";
      stat.append(b, span);
      container.append(stat);
      return;
    }

    // Key-Value
    if (primitive === "key-value") {
      const block = document.createElement("div");
      block.className = "pulse-status widget-kv";
      if (typeof p.value === "object" && p.value !== null) {
        const table = document.createElement("table");
        table.className = "candidate-table";
        const tbody = document.createElement("tbody");
        for (const key of Object.keys(p.value)) {
          const row = document.createElement("tr");
          const th = document.createElement("td");
          th.style.color = "var(--dim)";
          th.style.width = "35%";
          th.textContent = key.replace(/_/g, " ");
          const td = document.createElement("td");
          const v = p.value[key];
          td.textContent = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v !== undefined ? v : "-");
          row.append(th, td);
          tbody.append(row);
        }
        table.append(tbody);
        block.append(table);
      } else {
        block.textContent = p.value !== undefined ? String(p.value) : "";
      }
      container.append(block);
      return;
    }

    // Table
    if (primitive === "table") {
      const rows = Array.isArray(p.rows) ? p.rows : [];
      const group = document.createElement("div");
      group.className = "candidate-group";

      const heading = document.createElement("h3");
      heading.textContent = (p.label || "Table") + " (" + rows.length + ")";
      group.append(heading);

      if (!rows.length) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No rows.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      const table = document.createElement("table");
      table.className = "candidate-table";
      const columns = p.columns || (rows[0] ? Object.keys(rows[0]) : []);

      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      columns.forEach(function (col) {
        const th = document.createElement("th");
        th.textContent = String(col).replace(/_/g, " ");
        headRow.append(th);
      });
      thead.append(headRow);
      table.append(thead);

      const tbody = document.createElement("tbody");
      rows.forEach(function (item) {
        const tr = document.createElement("tr");
        columns.forEach(function (col) {
          const td = document.createElement("td");
          const cellVal = item ? item[col] : undefined;
          td.textContent =
            typeof cellVal === "object" && cellVal !== null
              ? JSON.stringify(cellVal)
              : cellVal !== undefined
              ? String(cellVal)
              : "-";
          if (col === "title" && item && item.title) {
            td.title = item.title;
          }
          tr.append(td);
        });
        tbody.append(tr);
      });
      table.append(tbody);
      group.append(table);
      container.append(group);
      return;
    }

    // List
    if (primitive === "list") {
      const items = Array.isArray(p.items) ? p.items : [];
      const group = document.createElement("div");
      group.className = "candidate-group";

      const heading = document.createElement("h3");
      heading.textContent = (p.label || "List") + " (" + items.length + ")";
      group.append(heading);

      if (!items.length) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No items.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      const ul = document.createElement("ul");
      ul.className = "widget-list-items";
      items.forEach(function (item) {
        const li = document.createElement("li");
        li.textContent = typeof item === "object" && item !== null ? JSON.stringify(item) : String(item);
        ul.append(li);
      });
      group.append(ul);
      container.append(group);
      return;
    }

    // Bar Chart
    if (primitive === "bar") {
      const group = document.createElement("div");
      group.className = "candidate-group widget-chart-bar";

      if (p.label) {
        const heading = document.createElement("h3");
        heading.textContent = p.label;
        group.append(heading);
      }

      const rawValues = p.values;
      if (!Array.isArray(rawValues) || rawValues.length === 0) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No data.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      const categories = Array.isArray(p.categories) ? p.categories : [];
      const items = [];

      for (let i = 0; i < rawValues.length; i++) {
        const item = rawValues[i];
        const catName = categories[i] !== undefined ? String(categories[i]) : "";
        if (typeof item === "number") {
          items.push({ name: catName || ("Item " + (i + 1)), value: item });
        } else if (item && typeof item === "object") {
          const name = item.name || item.label || item.model || item.id || catName || ("Item " + (i + 1));
          const val = item.tokens !== undefined ? item.tokens :
                      item.cost_usd !== undefined ? item.cost_usd :
                      item.value !== undefined ? item.value :
                      (item.tokens_in || 0) + (item.tokens_out || 0);
          items.push({ name: String(name), value: Number(val) || 0 });
        }
      }

      if (items.length === 0) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No data.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      let maxVal = 0;
      for (let i = 0; i < items.length; i++) {
        if (items[i].value > maxVal) maxVal = items[i].value;
      }
      if (maxVal <= 0) maxVal = 1;

      const chartBox = document.createElement("div");
      chartBox.className = "chart-bars-container";

      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        const row = document.createElement("div");
        row.className = "chart-bar-row";

        const labelSpan = document.createElement("span");
        labelSpan.className = "chart-bar-label";
        labelSpan.textContent = it.name;
        labelSpan.title = it.name;

        const track = document.createElement("div");
        track.className = "chart-bar-track";

        const fill = document.createElement("div");
        const pct = Math.min(100, Math.max(0, (it.value / maxVal) * 100));
        fill.className = "chart-bar-fill" + (i === items.length - 1 ? " chart-latest pulse-dot" : "");
        fill.style.width = pct.toFixed(1) + "%";

        track.append(fill);

        const valSpan = document.createElement("span");
        valSpan.className = "chart-bar-value";
        valSpan.textContent = typeof it.value === "number" && it.value % 1 !== 0
          ? "$" + it.value.toFixed(2)
          : Number(it.value).toLocaleString();

        row.append(labelSpan, track, valSpan);
        chartBox.append(row);
      }

      group.append(chartBox);
      container.append(group);
      return;
    }

    // Line Chart
    if (primitive === "line") {
      const group = document.createElement("div");
      group.className = "candidate-group widget-chart-line";

      if (p.label) {
        const heading = document.createElement("h3");
        heading.textContent = p.label;
        group.append(heading);
      }

      const rawSeries = p.series;
      if (!Array.isArray(rawSeries) || rawSeries.length === 0) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No data.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      const points = Array.isArray(p.points) ? p.points : [];
      const values = [];
      const pointLabels = [];

      for (let i = 0; i < rawSeries.length; i++) {
        const item = rawSeries[i];
        const ptName = points[i] !== undefined ? String(points[i]) : "";
        if (typeof item === "number") {
          values.push(item);
          pointLabels.push(ptName);
        } else if (item && typeof item === "object") {
          const name = item.at || item.point || item.label || ptName || ("P" + (i + 1));
          const val = item.tokens !== undefined ? item.tokens :
                      item.cost_usd !== undefined ? item.cost_usd :
                      item.value !== undefined ? item.value : 0;
          values.push(Number(val) || 0);
          pointLabels.push(String(name));
        }
      }

      if (values.length === 0) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No data.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      let minVal = values[0];
      let maxVal = values[0];
      for (let i = 1; i < values.length; i++) {
        if (values[i] < minVal) minVal = values[i];
        if (values[i] > maxVal) maxVal = values[i];
      }
      const range = maxVal - minVal || 1;

      const svgW = 260;
      const svgH = 64;
      const padX = 12;
      const padY = 8;
      const innerW = svgW - padX * 2;
      const innerH = svgH - padY * 2;

      const coords = [];
      for (let i = 0; i < values.length; i++) {
        const x = values.length === 1 ? padX + innerW / 2 : padX + (i / (values.length - 1)) * innerW;
        const y = padY + innerH - ((values[i] - minVal) / range) * innerH;
        coords.push({ x: x, y: y, val: values[i], label: pointLabels[i] || "" });
      }

      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 " + svgW + " " + svgH);
      svg.setAttribute("class", "chart-line-svg");
      svg.style.width = "100%";
      svg.style.height = "70px";
      svg.style.overflow = "visible";

      // Polyline
      const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      const ptsStr = coords.map(function (c) { return c.x.toFixed(1) + "," + c.y.toFixed(1); }).join(" ");
      polyline.setAttribute("points", ptsStr);
      polyline.setAttribute("fill", "none");
      polyline.setAttribute("stroke", "var(--accent)");
      polyline.setAttribute("stroke-width", "2");
      polyline.setAttribute("stroke-linecap", "round");
      polyline.setAttribute("stroke-linejoin", "round");
      polyline.setAttribute("pathLength", "300"); // issue #377: normalizes length so the CSS draw-in dasharray/dashoffset works regardless of geometry
      svg.append(polyline);

      // Dots
      for (let i = 0; i < coords.length; i++) {
        const c = coords[i];
        const isLatest = (i === coords.length - 1);
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", c.x.toFixed(1));
        circle.setAttribute("cy", c.y.toFixed(1));
        circle.setAttribute("r", isLatest ? "4" : "3");
        circle.setAttribute("fill", isLatest ? "var(--ok)" : "var(--accent)");
        circle.setAttribute("class", isLatest ? "pulse-dot chart-latest" : "chart-dot");

        const titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title");
        titleEl.textContent = (c.label ? c.label + ": " : "") + (typeof c.val === "number" && c.val % 1 !== 0 ? "$" + c.val.toFixed(2) : c.val.toLocaleString());
        circle.append(titleEl);

        svg.append(circle);
      }

      group.append(svg);

      if (pointLabels.some(Boolean)) {
        const labelsRow = document.createElement("div");
        labelsRow.className = "chart-line-points-row";
        labelsRow.style.display = "flex";
        labelsRow.style.justifyContent = "space-between";
        labelsRow.style.fontSize = "9px";
        labelsRow.style.color = "var(--dim)";
        labelsRow.style.marginTop = "2px";

        for (let i = 0; i < pointLabels.length; i++) {
          const ptSpan = document.createElement("span");
          ptSpan.textContent = pointLabels[i] || "";
          labelsRow.append(ptSpan);
        }
        group.append(labelsRow);
      }

      container.append(group);
      return;
    }

    // Swimlane
    if (primitive === "swimlane") {
      const rows = Array.isArray(p.rows) ? p.rows : [];
      const group = document.createElement("div");
      group.className = "candidate-group swimlane swimlane-container";

      const heading = document.createElement("h3");
      heading.className = "swimlane-header";
      heading.textContent = (p.label || "Swimlanes") + " (" + rows.length + ")";
      group.append(heading);

      if (!rows.length) {
        const emptyDiv = document.createElement("div");
        emptyDiv.className = "empty";
        emptyDiv.textContent = p.empty || "No swimlanes.";
        group.append(emptyDiv);
        container.append(group);
        return;
      }

      const columns = Array.isArray(p.columns) && p.columns.length ? p.columns : ["Lane", "Tasks"];
      const colHeader = document.createElement("div");
      colHeader.className = "swimlane-columns";
      const col1 = document.createElement("div");
      col1.textContent = columns[0] || "Lane";
      const col2 = document.createElement("div");
      col2.textContent = columns.slice(1).join(" / ") || "Tasks";
      colHeader.append(col1, col2);
      group.append(colHeader);

      const tableBox = document.createElement("div");
      tableBox.className = "swimlane-table";

      rows.forEach(function (row) {
        if (!row) return;
        const laneEl = document.createElement("div");
        laneEl.className = "swimlane-lane lane";

        const labelCell = document.createElement("div");
        labelCell.className = "swimlane-label";
        const laneName = row.label || row.name || row.id || "Lane";
        const laneRuntime = row.runtime ? " (" + row.runtime + ")" : "";
        labelCell.textContent = laneName + laneRuntime;
        labelCell.title = laneName + (row.status ? " - " + row.status : "");

        const trackCell = document.createElement("div");
        trackCell.className = "swimlane-track";

        const trackLine = document.createElement("div");
        trackLine.className = "swimlane-track-line";
        trackCell.append(trackLine);

        const items = row.items || row.tasks || [];
        if (Array.isArray(items) && items.length) {
          items.forEach(function (item) {
            if (!item) return;
            const marker = document.createElement("div");
            const itemTitle = item.title || item.name || item.id || item.label || "task";
            const itemState = String(item.state || item.status || "").toLowerCase();
            const isActive = Boolean(item.active) || itemState === "running";

            let markerClass = "marker swimlane-marker";
            if (isActive) {
              markerClass += " active running";
            } else if (itemState === "done" || itemState === "completed") {
              markerClass += " done";
            } else if (itemState === "blocked" || itemState === "error") {
              markerClass += " blocked";
            } else if (itemState === "queued" || itemState === "pending") {
              markerClass += " queued";
            }

            marker.className = markerClass;

            const iconSpan = document.createElement("span");
            iconSpan.className = "marker-icon";
            iconSpan.textContent = isActive ? "\u25cf" : (itemState === "done" ? "\u2713" : "\u25cb");
            marker.append(iconSpan);

            const titleSpan = document.createElement("span");
            titleSpan.className = "marker-title";
            titleSpan.textContent = itemTitle;
            marker.append(titleSpan);

            if (item.progress !== undefined && item.progress !== null) {
              const progSpan = document.createElement("span");
              progSpan.className = "marker-progress";
              progSpan.style.fontSize = "9px";
              progSpan.style.opacity = "0.75";
              progSpan.textContent = item.progress + "%";
              marker.append(progSpan);
            }

            trackCell.append(marker);
          });
        } else {
          const idleSpan = document.createElement("span");
          idleSpan.className = "marker swimlane-marker queued";
          idleSpan.textContent = "idle";
          trackCell.append(idleSpan);
        }

        laneEl.append(labelCell, trackCell);
        tableBox.append(laneEl);
      });

      group.append(tableBox);
      container.append(group);
      return;
    }

    // Empty state
    if (primitive === "empty-state") {
      const el = document.createElement("div");
      el.className = "empty";
      el.textContent = p.message || "Empty";
      container.append(el);
      return;
    }

    // Error state
    if (primitive === "error-state") {
      const el = document.createElement("div");
      el.className = "pulse-status error";
      el.textContent = p.message || "Error";
      container.append(el);
      return;
    }

    // Divider
    if (primitive === "divider") {
      const hr = document.createElement("hr");
      hr.className = "widget-divider";
      container.append(hr);
      return;
    }

    // Spacer
    if (primitive === "spacer") {
      const sp = document.createElement("div");
      sp.className = "widget-spacer";
      container.append(sp);
      return;
    }

    // Fallback for unknown / action primitives
    const fb = document.createElement("div");
    fb.className = "pulse-status";
    fb.textContent = (p.label || p.value || primitive);
    container.append(fb);
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Format CLI output JSON matching CLI print behavior for side-by-side view.
   */
  function formatCliOutput(artifact) {
    if (!artifact) return "{}";
    const tree = artifact.render || artifact;
    return JSON.stringify(tree, null, 2);
  }

  /**
   * Bundled default visual tokens fallback.
   * Encodes the dark-theme defaults shared across browser, maker, and CLI surfaces.
   */
  const DEFAULT_TOKENS = {
    schema_version: 1,
    colors: {
      background: "#080b14",
      surface: "#101522",
      layer: "#ffffff0d",
      hover: "#ffffff15",
      stroke: "#29324a",
      strong: "#3a4562",
      text: "#f4f7ff",
      muted: "#aab3c5",
      dim: "#8792a8",
      accent: "#4d6bfe",
      blue: "#3151d8",
      ok: "#68d391",
      warn: "#f6c85f",
      bad: "#ff7a90"
    },
    typography: {
      sans: ["Inter", "Segoe UI Variable", "Segoe UI", "sans-serif"],
      mono: ["Cascadia Code", "Cascadia Mono", "Consolas", "monospace"],
      size_base: "12px",
      size_small: "10px",
      size_heading: "14px",
      weight_normal: 400,
      weight_bold: 600
    },
    spacing: {
      unit: "4px",
      gap_small: "4px",
      gap_medium: "8px",
      gap_large: "16px",
      padding_small: "6px",
      padding_medium: "12px"
    },
    radius: {
      small: "4px",
      medium: "6px",
      large: "12px"
    },
    density: {
      row_height: "28px",
      card_max_height: "520px",
      grid_min_card_width: "280px"
    },
    effects: {
      glow_ok: "rgba(104, 211, 145, 0.55)",
      glow_warn: "rgba(246, 200, 95, 0.5)",
      glow_bad: "rgba(255, 122, 144, 0.5)",
      glow_accent: "rgba(77, 107, 254, 0.55)",
      sheen_top: "rgba(255, 255, 255, 0.07)",
      shadow_panel: "0 12px 32px rgba(0, 0, 0, 0.45)",
      shadow_instrument: "0 24px 64px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.06)",
      shadow_lift: "0 2px 10px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05)",
      bezel: "inset 0 0 0 1px rgba(255, 255, 255, 0.03), inset 0 -10px 24px rgba(0, 0, 0, 0.25)"
    },
    motion: {
      duration_fast: "120ms",
      duration_medium: "200ms",
      duration_live: "1600ms",
      easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
      easing_pulse: "ease-in-out"
    },
    backdrop: {
      grid: "linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px)",
      grid_size: "28px",
      scanline: "repeating-linear-gradient(0deg, rgba(0, 0, 0, 0.14) 0 1px, transparent 1px 3px)",
      vignette: "radial-gradient(120% 90% at 50% 0%, rgba(32, 43, 80, 0.35) 0%, transparent 60%)"
    }
  };

  /**
   * Returns a copy of the bundled default visual tokens.
   */
  function defaultTokens() {
    return JSON.parse(JSON.stringify(DEFAULT_TOKENS));
  }

  /**
   * Apply visual tokens to a DOM element (defaults to document.documentElement :root).
   * Sets both --token-* custom properties and base theme variables for backward compatibility.
   */
  function applyTokens(tokens, target) {
    if (!tokens || typeof tokens !== "object") return;
    const el = target || (typeof document !== "undefined" && document.documentElement ? document.documentElement : null);
    if (!el || !el.style || typeof el.style.setProperty !== "function") return;

    if (tokens.colors && typeof tokens.colors === "object") {
      const c = tokens.colors;
      if (c.background) { el.style.setProperty("--token-bg", c.background); el.style.setProperty("--token-background", c.background); el.style.setProperty("--background", c.background); }
      if (c.surface) { el.style.setProperty("--token-surface", c.surface); el.style.setProperty("--surface", c.surface); }
      if (c.layer) { el.style.setProperty("--token-layer", c.layer); el.style.setProperty("--layer", c.layer); }
      if (c.hover) { el.style.setProperty("--token-hover", c.hover); el.style.setProperty("--hover", c.hover); }
      if (c.stroke) { el.style.setProperty("--token-stroke", c.stroke); el.style.setProperty("--stroke", c.stroke); }
      if (c.strong) { el.style.setProperty("--token-strong", c.strong); el.style.setProperty("--strong", c.strong); }
      if (c.text) { el.style.setProperty("--token-text", c.text); el.style.setProperty("--text", c.text); }
      if (c.muted) { el.style.setProperty("--token-muted", c.muted); el.style.setProperty("--muted", c.muted); }
      if (c.dim) { el.style.setProperty("--token-dim", c.dim); el.style.setProperty("--dim", c.dim); }
      if (c.accent) { el.style.setProperty("--token-accent", c.accent); el.style.setProperty("--accent", c.accent); }
      if (c.blue) { el.style.setProperty("--token-blue", c.blue); el.style.setProperty("--blue", c.blue); }
      if (c.ok) { el.style.setProperty("--token-ok", c.ok); el.style.setProperty("--ok", c.ok); }
      if (c.warn) { el.style.setProperty("--token-warn", c.warn); el.style.setProperty("--warn", c.warn); }
      if (c.bad) { el.style.setProperty("--token-bad", c.bad); el.style.setProperty("--bad", c.bad); }
    }

    if (tokens.typography && typeof tokens.typography === "object") {
      const t = tokens.typography;
      if (t.sans) {
        const sansVal = Array.isArray(t.sans) ? t.sans.join(", ") : String(t.sans);
        el.style.setProperty("--token-font-sans", sansVal);
        el.style.setProperty("--sans", sansVal);
      }
      if (t.mono) {
        const monoVal = Array.isArray(t.mono) ? t.mono.join(", ") : String(t.mono);
        el.style.setProperty("--token-font-mono", monoVal);
        el.style.setProperty("--mono", monoVal);
      }
      if (t.size_base !== undefined) el.style.setProperty("--token-size-base", typeof t.size_base === "number" ? t.size_base + "px" : String(t.size_base));
      if (t.size_small !== undefined) el.style.setProperty("--token-size-small", typeof t.size_small === "number" ? t.size_small + "px" : String(t.size_small));
      if (t.size_heading !== undefined) el.style.setProperty("--token-size-heading", typeof t.size_heading === "number" ? t.size_heading + "px" : String(t.size_heading));
      if (t.weight_normal !== undefined) el.style.setProperty("--token-weight-normal", String(t.weight_normal));
      if (t.weight_bold !== undefined) el.style.setProperty("--token-weight-bold", String(t.weight_bold));
    }

    if (tokens.spacing && typeof tokens.spacing === "object") {
      const s = tokens.spacing;
      if (s.unit !== undefined) el.style.setProperty("--token-unit", typeof s.unit === "number" ? s.unit + "px" : String(s.unit));
      if (s.gap_small !== undefined) el.style.setProperty("--token-gap-small", typeof s.gap_small === "number" ? s.gap_small + "px" : String(s.gap_small));
      if (s.gap_medium !== undefined) {
        const gapVal = typeof s.gap_medium === "number" ? s.gap_medium + "px" : String(s.gap_medium);
        el.style.setProperty("--token-gap-medium", gapVal);
        el.style.setProperty("--token-gap", gapVal);
      }
      if (s.gap_large !== undefined) el.style.setProperty("--token-gap-large", typeof s.gap_large === "number" ? s.gap_large + "px" : String(s.gap_large));
      if (s.padding_small !== undefined) el.style.setProperty("--token-padding-small", typeof s.padding_small === "number" ? s.padding_small + "px" : String(s.padding_small));
      if (s.padding_medium !== undefined) el.style.setProperty("--token-padding-medium", typeof s.padding_medium === "number" ? s.padding_medium + "px" : String(s.padding_medium));
    }

    if (tokens.radius && typeof tokens.radius === "object") {
      const r = tokens.radius;
      if (r.small !== undefined) el.style.setProperty("--token-radius-small", typeof r.small === "number" ? r.small + "px" : String(r.small));
      if (r.medium !== undefined) {
        const radVal = typeof r.medium === "number" ? r.medium + "px" : String(r.medium);
        el.style.setProperty("--token-radius-medium", radVal);
        el.style.setProperty("--token-radius", radVal);
      }
      if (r.large !== undefined) el.style.setProperty("--token-radius-large", typeof r.large === "number" ? r.large + "px" : String(r.large));
    }

    if (tokens.density && typeof tokens.density === "object") {
      const d = tokens.density;
      if (d.row_height !== undefined) el.style.setProperty("--token-row-height", typeof d.row_height === "number" ? d.row_height + "px" : String(d.row_height));
      if (d.card_max_height !== undefined) el.style.setProperty("--token-card-max-height", typeof d.card_max_height === "number" ? d.card_max_height + "px" : String(d.card_max_height));
      if (d.grid_min_card_width !== undefined) el.style.setProperty("--token-grid-min-card-width", typeof d.grid_min_card_width === "number" ? d.grid_min_card_width + "px" : String(d.grid_min_card_width));
    }

    if (tokens.effects && typeof tokens.effects === "object") {
      const e = tokens.effects;
      const effectKeys = {
        glow_ok: "--glow-ok", glow_warn: "--glow-warn", glow_bad: "--glow-bad", glow_accent: "--glow-accent",
        sheen_top: "--sheen-top", shadow_panel: "--shadow-panel", shadow_instrument: "--shadow-instrument",
        shadow_lift: "--shadow-lift", bezel: "--bezel"
      };
      for (const key in effectKeys) {
        if (e[key] !== undefined) {
          el.style.setProperty(effectKeys[key], String(e[key]));
          el.style.setProperty("--token-" + key.replace(/_/g, "-"), String(e[key]));
        }
      }
    }

    if (tokens.motion && typeof tokens.motion === "object") {
      const m = tokens.motion;
      if (m.duration_fast !== undefined) el.style.setProperty("--duration-fast", typeof m.duration_fast === "number" ? m.duration_fast + "ms" : String(m.duration_fast));
      if (m.duration_medium !== undefined) el.style.setProperty("--duration-medium", typeof m.duration_medium === "number" ? m.duration_medium + "ms" : String(m.duration_medium));
      if (m.duration_live !== undefined) el.style.setProperty("--duration-live", typeof m.duration_live === "number" ? m.duration_live + "ms" : String(m.duration_live));
      if (m.easing !== undefined) el.style.setProperty("--easing", String(m.easing));
      if (m.easing_pulse !== undefined) el.style.setProperty("--easing-pulse", String(m.easing_pulse));
    }

    if (tokens.backdrop && typeof tokens.backdrop === "object") {
      const b = tokens.backdrop;
      if (b.grid !== undefined) el.style.setProperty("--backdrop-grid", String(b.grid));
      if (b.grid_size !== undefined) el.style.setProperty("--backdrop-grid-size", typeof b.grid_size === "number" ? b.grid_size + "px" : String(b.grid_size));
      if (b.scanline !== undefined) el.style.setProperty("--backdrop-scanline", String(b.scanline));
      if (b.vignette !== undefined) el.style.setProperty("--backdrop-vignette", String(b.vignette));
    }
  }

  // Automatically apply default tokens on DOM load if running in browser
  if (typeof document !== "undefined" && document.documentElement) {
    applyTokens(DEFAULT_TOKENS);
  }

  /**
   * Stepper for multi-state living fixture demo sequences.
   */
  function createSequenceStepper(states, callback, intervalMs) {
    if (!Array.isArray(states) || states.length === 0) return null;
    let index = 0;
    const timer = setInterval(function () {
      index = (index + 1) % states.length;
      callback(states[index], index);
    }, intervalMs || 2500);
    return {
      stop: function () { clearInterval(timer); },
      getIndex: function () { return index; },
    };
  }

  /**
   * Start a living demo timer that cycles through fixture states.
   */
  function startLivingDemo(spec, fixtureData, container, options) {
    options = options || {};
    const intervalMs = options.intervalMs || 3000;
    const sequence = (fixtureData && Array.isArray(fixtureData.sequence)) ? fixtureData.sequence : null;
    if (!sequence || sequence.length <= 1) {
      const rendered = renderSpec(spec, fixtureData);
      container.innerHTML = "";
      renderNodeToDom(rendered.render, container, options);
      return null;
    }
    let step = 0;
    function tick() {
      const currentSnapshot = sequence[step % sequence.length];
      const boundData = Object.assign({}, fixtureData, { agents: currentSnapshot });
      const rendered = renderSpec(spec, boundData);
      container.innerHTML = "";
      renderNodeToDom(rendered.render, container, options);
      step++;
    }
    tick();
    const timerId = setInterval(tick, intervalMs);
    return {
      stop: function () { clearInterval(timerId); },
      getStep: function () { return step; },
    };
  }

  return {
    resolvePointer: resolvePointer,
    parseYamlSubset: parseYamlSubset,
    renderSpec: renderSpec,
    renderNodeToDom: renderNodeToDom,
    formatCliOutput: formatCliOutput,
    DEFAULT_TOKENS: DEFAULT_TOKENS,
    defaultTokens: defaultTokens,
    applyTokens: applyTokens,
    createSequenceStepper: createSequenceStepper,
    startLivingDemo: startLivingDemo,
  };
});
