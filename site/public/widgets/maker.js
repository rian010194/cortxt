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
      background: "#101216",
      surface: "#181b20",
      layer: "#ffffff0d",
      hover: "#ffffff15",
      stroke: "#5b6471",
      strong: "#727c8a",
      text: "#e7ebf0",
      muted: "#8d97a3",
      dim: "#65717f",
      accent: "#8fa3c7",
      blue: "#7885a7",
      ok: "#a8d5ba",
      warn: "#d8c49a",
      bad: "#d9a6b2"
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
   * WCAG relative luminance / contrast helpers (mirrors
   * widget_contract/tokens.py's `_relative_luminance`/`contrast_ratio` --
   * kept in sync by hand since this file has no build step to share Python).
   * Used to pick a text color that actually clears AA contrast against the
   * `--blue`-to-`--accent` gradient (issue #376 review finding 2): no
   * single literal color clears 4.5:1 across every preset -- the shipped
   * v1 default palette's blue/accent are dark/saturated (wants light text)
   * while the visual-tokens.v2 presets' blue/accent are pastel/lighter
   * (wants dark text) -- so this picks whichever of black/white maximizes
   * the worst-case contrast against the actual resolved colors instead of
   * hardcoding one.
   */
  function _hexToRgb(hex) {
    if (typeof hex !== "string") return null;
    let v = hex.trim();
    if (v[0] !== "#") return null;
    v = v.slice(1);
    if (v.length === 4 || v.length === 8) v = v.slice(0, v.length === 4 ? 3 : 6);
    if (v.length === 3) v = v.split("").map(function (ch) { return ch + ch; }).join("");
    if (v.length !== 6) return null;
    const num = parseInt(v, 16);
    if (Number.isNaN(num)) return null;
    return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
  }

  function _srgbChannelToLinear(channel) {
    const c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  function _relativeLuminance(hex) {
    const rgb = _hexToRgb(hex);
    if (!rgb) return null;
    return 0.2126 * _srgbChannelToLinear(rgb.r) + 0.7152 * _srgbChannelToLinear(rgb.g) + 0.0722 * _srgbChannelToLinear(rgb.b);
  }

  function _contrastRatio(hexA, hexB) {
    const la = _relativeLuminance(hexA);
    const lb = _relativeLuminance(hexB);
    if (la === null || lb === null) return null;
    const lighter = Math.max(la, lb);
    const darker = Math.min(la, lb);
    return (lighter + 0.05) / (darker + 0.05);
  }

  /**
   * Pick whichever of black/white maximizes the worst-case (minimum)
   * contrast ratio against every color in `hexColors`. Falls back to
   * `fallback` (default white) if none of the colors are parseable.
   */
  function pickReadableTextColor(hexColors, fallback) {
    const candidates = ["#000000", "#ffffff"];
    let best = fallback || "#ffffff";
    let bestScore = -1;
    candidates.forEach(function (candidate) {
      let minRatio = Infinity;
      let any = false;
      (hexColors || []).forEach(function (bg) {
        const ratio = _contrastRatio(candidate, bg);
        if (ratio !== null) {
          any = true;
          minRatio = Math.min(minRatio, ratio);
        }
      });
      if (any && minRatio > bestScore) {
        bestScore = minRatio;
        best = candidate;
      }
    });
    return best;
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
      if (c.blue && c.accent) {
        // Text sitting on the .swimlane .marker.running / .active
        // linear-gradient(--blue, --accent) fill -- see pickReadableTextColor.
        el.style.setProperty("--marker-running-text", pickReadableTextColor([c.blue, c.accent], "#ffffff"));
      }
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

  /**
   * Maker Studio: mounts the widget gallery / spec studio / tokens editor /
   * import panel into a host container (index.html's fixed left pane,
   * issue #369). Ported from the former standalone maker.html -- markup and
   * logic unchanged in substance, only: (a) scoped under .maker-pane instead
   * of :root/body so it inherits the host page's design tokens rather than
   * redefining them, and (b) inline onclick/oninput attributes replaced with
   * addEventListener wiring since this now lives in a closure, not a page
   * with global functions.
   */
  var PRESETS = {
    candidates: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: candidates\n  version: \"0.1\"\n  title: Candidates\ndata:\n  reads:\n    - id: candidates\n      source: github\n      operation: candidates.view.v1\n      input:\n        repo: owner/repo\n      select: []\n      refresh:\n        mode: manual\n      output_type: candidates.view.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Candidates}\n  children:\n    - primitive: key-value\n      bindings: {value: {read: candidates, pointer: /source, type: core.object.v1}}\n    - primitive: metric\n      props: {label: Total}\n      bindings: {value: {read: candidates, pointer: /total, type: core.number.v1}}\n    - primitive: table\n      props: {label: frontier, columns: [number, title, workflow, area, milestone, open_blocker_count]}\n      bindings: {rows: {read: candidates, pointer: /groups/0/rows, type: core.array.v1}}\n    - primitive: table\n      props: {label: other, columns: [number, title, workflow, area, milestone, open_blocker_count]}\n      bindings: {rows: {read: candidates, pointer: /groups/3/rows, type: core.array.v1}}\nactions: []\ncapabilities: [read:issues]",
      data: {
        candidates: {
          schema_version: 1,
          source: { complete: true, status: "fresh", age_seconds: 0, error: null },
          total: 2,
          groups: [
            { id: "frontier", count: 1, rows: [{ number: 1, title: "Issue 1", workflow: "workflow:ready", area: null, milestone: "M1", open_blocker_count: 0 }] },
            { id: "in_progress", count: 0, rows: [] },
            { id: "blocked", count: 0, rows: [] },
            { id: "other", count: 1, rows: [{ number: 2, title: "Issue 2", workflow: "workflow:inbox", area: null, milestone: null, open_blocker_count: 0 }] }
          ]
        }
      },
      hint: "cortxt widget --view candidates --repo OWNER/REPO"
    },
    pulse: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: session-pulse\n  version: \"0.1\"\n  title: Session Pulse\ndata:\n  reads:\n    - id: snapshot\n      source: store\n      operation: sessions.snapshot.v2\n      input: {}\n      select: []\n      refresh:\n        mode: poll\n        interval_seconds: 5\n      output_type: sessions.snapshot.v2\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Session Pulse}\n  children:\n    - primitive: key-value\n      bindings:\n        value: {read: snapshot, pointer: /orchestrator, type: core.object.v1}\n    - primitive: metric\n      props: {label: Active sessions}\n      bindings:\n        value: {read: snapshot, pointer: /orchestrator/active_agent_sessions, type: core.number.v1}\n    - primitive: table\n      props: {label: Workstreams, columns: [workstream_id, status, updated_at]}\n      bindings:\n        rows: {read: snapshot, pointer: /workstreams, type: core.array.v1}\n    - primitive: table\n      props: {label: Activity, columns: [timestamp, event_type, workstream_id, actor]}\n      bindings:\n        rows: {read: snapshot, pointer: /activity, type: core.array.v1}\nactions: []\ncapabilities: [read:sessions]",
      data: {
        snapshot: {
          schema_version: 2,
          generated_at: "2026-08-23T18:00:00Z",
          orchestrator: { status: "idle", active_agent_sessions: 2, message: "2 active runs" },
          workstreams: [
            { workstream_id: "ws-builder-339", status: "running", updated_at: "2026-08-23T19:00:00Z" },
            { workstream_id: "ws-atlas-sync", status: "idle", updated_at: "2026-08-23T18:55:00Z" }
          ],
          activity: [
            { timestamp: "2026-08-23T19:00:00Z", event_type: "turn_completed", workstream_id: "ws-builder-339", actor: "builder" }
          ]
        }
      },
      hint: "cortxt widget --view session-pulse"
    },
    map: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: execution-map\n  version: \"0.1\"\n  title: Execution Map\ndata:\n  reads:\n    - id: plan\n      source: store\n      operation: execution-map.plan.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: execution-map.plan.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Execution Map}\n  children:\n    - primitive: text\n      props: {label: Role}\n      bindings:\n        value: {read: plan, pointer: /role, type: core.string.v1}\n    - primitive: table\n      props: {label: Issues, columns: [id, wave, blockers, drift_codes, launchable]}\n      bindings:\n        rows: {read: plan, pointer: /issues, type: core.array.v1}\n    - primitive: table\n      props: {label: Claims, columns: [claim_id, issue_id, run_id, state, driver_id]}\n      bindings:\n        rows: {read: plan, pointer: /claims, type: core.array.v1}\n    - primitive: list\n      props: {label: Waves, empty: No waves}\n      bindings:\n        items: {read: plan, pointer: /waves, type: core.array.v1}\nactions: []\ncapabilities: [read:execution-map]",
      data: {
        plan: {
          role: "builder",
          issues: [
            { id: "339", wave: 1, blockers: [], drift_codes: [], launchable: true },
            { id: "342", wave: 2, blockers: ["339"], drift_codes: [], launchable: false }
          ],
          claims: [
            { claim_id: "claim-339", issue_id: "339", run_id: "run-001", state: "active", driver_id: "builder-1" }
          ],
          waves: [["339"], ["342"]],
          collision_codes: []
        }
      },
      hint: "cortxt widget --view execution-map --plan-input <file>"
    },
    docker: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: docker-status\n  version: \"0.1\"\n  title: Docker Status\ndata:\n  reads:\n    - id: docker\n      source: store\n      operation: docker.status.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: docker.status.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Docker Status}\n  children:\n    - primitive: key-value\n      bindings:\n        value: {read: docker, pointer: /engine, type: core.object.v1}\n    - primitive: metric\n      props: {label: Running}\n      bindings:\n        value: {read: docker, pointer: /running_containers, type: core.number.v1}\n    - primitive: metric\n      props: {label: Total}\n      bindings:\n        value: {read: docker, pointer: /total_containers, type: core.number.v1}\n    - primitive: table\n      props: {label: Containers, columns: [id, name, image, status]}\n      bindings:\n        rows: {read: docker, pointer: /containers, type: core.array.v1}\n    - primitive: list\n      props: {label: Images, empty: No images}\n      bindings:\n        items: {read: docker, pointer: /images, type: core.array.v1}\nactions: []\ncapabilities: [read:docker]",
      data: {
        docker: {
          schema_version: 1,
          engine: { server_version: "27.1.1", os: "linux", architecture: "x86_64", status: "running" },
          containers: [
            { id: "c1a2b3c4d5e6", name: "cortxt-redis", image: "redis:7-alpine", status: "Up 2 hours" },
            { id: "f7e8d9c0b1a2", name: "cortxt-postgres", image: "postgres:16-alpine", status: "Up 2 hours" }
          ],
          images: ["redis:7-alpine", "postgres:16-alpine", "cortxt/worker:v1"],
          total_containers: 3,
          running_containers: 2
        }
      },
      hint: "cortxt widget --view docker-status"
    },
    webhooks: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: webhooks\n  version: \"0.1\"\n  title: Webhooks\ndata:\n  reads:\n    - id: webhooks\n      source: store\n      operation: webhooks.status.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: webhooks.status.v1\n      on_error: stale\n    - id: pages\n      source: store\n      operation: pages.deploys.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: pages.deploys.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Webhooks}\n  children:\n    - primitive: metric\n      props: {label: Active webhooks}\n      bindings:\n        value: {read: webhooks, pointer: /active, type: core.number.v1}\n    - primitive: table\n      props: {label: Hooks, columns: [id, url, events, active]}\n      bindings:\n        rows: {read: webhooks, pointer: /hooks, type: core.array.v1}\n    - primitive: key-value\n      bindings:\n        value: {read: pages, pointer: /latest, type: core.object.v1}\n    - primitive: table\n      props: {label: Deployments, columns: [id, environment, created_on, stage]}\n      bindings:\n        rows: {read: pages, pointer: /deployments, type: core.array.v1}\nactions: []\ncapabilities: [read:webhooks, read:pages]",
      data: {
        webhooks: {
          schema_version: 1,
          repo: "rian010194/cortxt",
          total: 2,
          active: 2,
          hooks: [
            { id: 101, url: "https://api.cloudflare.com/pages/deploy-hook/demo", events: ["push", "pull_request"], active: true },
            { id: 102, url: "https://notify.example.org/events", events: ["issues"], active: true }
          ]
        },
        pages: {
          schema_version: 1,
          project: "cortxt",
          account: "c7c04f119f81234dc3d851bf6ff2adfe",
          latest: { id: "dep-789", environment: "production", created_on: "2026-08-23T18:30:00Z", stage: "deploy", status: "success" },
          deployments: [
            { id: "dep-789", environment: "production", created_on: "2026-08-23T18:30:00Z", stage: "deploy" },
            { id: "dep-788", environment: "preview", created_on: "2026-08-23T17:45:00Z", stage: "deploy" }
          ]
        }
      },
      hint: "cortxt widget --view webhooks"
    },
    usage: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: usage-cost\n  version: \"0.1\"\n  title: Usage & Cost\ndata:\n  reads:\n    - id: usage\n      source: store\n      operation: usage-cost.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: usage-cost.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Usage & Cost}\n  children:\n    - primitive: metric\n      props: {label: Total cost}\n      bindings:\n        value: {read: usage, pointer: /total_cost_usd, type: core.number.v1}\n    - primitive: metric\n      props: {label: Total tokens}\n      bindings:\n        value: {read: usage, pointer: /total_tokens, type: core.number.v1}\n    - primitive: bar\n      props: {label: Tokens by runtime, categories: [Hermes, Codex, Claude, DSH]}\n      bindings:\n        values: {read: usage, pointer: /runtime_tokens, type: core.array.v1}\n    - primitive: bar\n      props: {label: Cost by model, categories: [hermes-3-70b, gpt-4o, claude-3-7-sonnet, deepseek-v3]}\n      bindings:\n        values: {read: usage, pointer: /model_costs, type: core.array.v1}\n    - primitive: line\n      props: {label: Usage over time, points: [\"10:00\", \"10:15\", \"10:30\", \"10:45\", \"11:00\"]}\n      bindings:\n        series: {read: usage, pointer: /history_tokens, type: core.array.v1}\nactions: []\ncapabilities: [read:usage-cost]",
      data: {
        usage: {
          schema_version: 1,
          period: "current",
          total_cost_usd: 0.42,
          total_tokens: 24800,
          runtimes: [
            { id: "hermes", name: "Hermes", tokens_in: 8000, tokens_out: 4000, cost_usd: 0.12, model: "hermes-3-70b", tokens: 12000 },
            { id: "codex", name: "Codex", tokens_in: 6000, tokens_out: 2500, cost_usd: 0.15, model: "gpt-4o", tokens: 8500 },
            { id: "claude", name: "Claude", tokens_in: 2000, tokens_out: 1200, cost_usd: 0.10, model: "claude-3-7-sonnet", tokens: 3200 },
            { id: "dsh", name: "DSH", tokens_in: 800, tokens_out: 300, cost_usd: 0.05, model: "deepseek-v3", tokens: 1100 }
          ],
          history: [
            { at: "10:00", tokens: 3000, cost_usd: 0.05 },
            { at: "10:15", tokens: 7500, cost_usd: 0.12 },
            { at: "10:30", tokens: 14000, cost_usd: 0.22 },
            { at: "10:45", tokens: 19500, cost_usd: 0.31 },
            { at: "11:00", tokens: 24800, cost_usd: 0.42 }
          ],
          runtime_tokens: [12000, 8500, 3200, 1100],
          runtime_names: ["Hermes", "Codex", "Claude", "DSH"],
          model_costs: [0.12, 0.15, 0.10, 0.05],
          model_names: ["hermes-3-70b", "gpt-4o", "claude-3-7-sonnet", "deepseek-v3"],
          history_tokens: [3000, 7500, 14000, 19500, 24800],
          history_points: ["10:00", "10:15", "10:30", "10:45", "11:00"],
          history_costs: [0.05, 0.12, 0.22, 0.31, 0.42]
        }
      },
      hint: "cortxt widget --view usage-cost"
    },
    agents: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: session-agents\n  version: \"0.1\"\n  title: Session Agents\ndata:\n  reads:\n    - id: agents\n      source: store\n      operation: session-agents.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: session-agents.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Session Agents}\n  children:\n    - primitive: heading\n      props: {value: Session Agents}\n    - primitive: text\n      props: {value: Live Multi-Agent Workspace}\n    - primitive: swimlane\n      props: {label: Agents, columns: [Agent, Tasks]}\n      bindings:\n        rows: {read: agents, pointer: /agents, type: core.array.v1}\nactions: []\ncapabilities: [read:session-agents]",
      data: {
        agents: {
          schema_version: 1,
          agents: [
            {
              id: "agent-hermes",
              name: "Hermes",
              runtime: "hermes",
              status: "running",
              current_task: "Execute session plan",
              tasks: [
                { id: "t1", title: "Load context", state: "done", progress: 100 },
                { id: "t2", title: "Execute session plan", state: "running", progress: 65 },
                { id: "t3", title: "Verification", state: "queued", progress: 0 }
              ]
            },
            {
              id: "agent-pi",
              name: "Pi",
              runtime: "pi",
              status: "running",
              current_task: "Analyze codebase invariants",
              tasks: [
                { id: "t4", title: "Inspect AST", state: "done", progress: 100 },
                { id: "t5", title: "Analyze codebase invariants", state: "running", progress: 40 }
              ]
            },
            {
              id: "agent-codex",
              name: "Codex",
              runtime: "codex",
              status: "done",
              current_task: null,
              tasks: [
                { id: "t6", title: "Contract validation", state: "done", progress: 100 }
              ]
            }
          ]
        }
      },
      hint: "cortxt widget --view session-agents"
    },
    compliance: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: compliance-audit\n  version: \"0.1\"\n  title: Compliance Audit\ndata:\n  reads:\n    - id: compliance\n      source: store\n      operation: compliance.report.v1\n      input: {}\n      select: []\n      refresh:\n        mode: manual\n      output_type: core.object.v1\n      on_error: stale\nrender:\n  primitive: stack\n  props: {label: Compliance Audit}\n  children:\n    - primitive: metric\n      props: {label: Score}\n      bindings:\n        value: {read: compliance, pointer: /score, type: core.number.v1}\n    - primitive: badge\n      bindings:\n        value: {read: compliance, pointer: /status, type: core.string.v1}\n    - primitive: table\n      props: {label: Controls, columns: [control_id, status, category]}\n      bindings:\n        rows: {read: compliance, pointer: /controls, type: core.array.v1}\nactions: []\ncapabilities: []",
      data: {
        compliance: {
          score: 98,
          status: "Passed",
          controls: [
            { control_id: "AC-1", status: "passed", category: "access_control" },
            { control_id: "AU-2", status: "passed", category: "audit_trail" },
            { control_id: "SC-7", status: "passed", category: "boundary_protection" }
          ]
        }
      },
      hint: "cortxt widget load --spec compliance.yaml --view loaded"
    },
    custom: {
      spec: "contract_version: \"0.1\"\nwidget:\n  id: custom-widget\n  version: \"0.1\"\n  title: Custom Widget\nrender:\n  primitive: stack\n  children:\n    - primitive: heading\n      props: {value: \"Hello Cortxt\"}\n    - primitive: metric\n      props: {label: \"Counter\", value: 42}",
      data: {},
      hint: "cortxt widget load --spec custom.yaml --view loaded"
    }
  };

  var MAKER_HTML =
    '<div class="maker-pane-header">' +
      '<div><a class="studio-back" href="/workspace/">← Work Console</a><span class="maker-pane-title">Customize Workstream view</span><div class="card-meta" style="margin-top:6px">WS-042 · Municipal AI Act gap analysis</div></div>' +
      '<div class="studio-links"><a href="/docs/widgets/">Widget documentation</a></div>' +
    '</div>' +
    '<div class="studio-context"><span>Placement</span><strong>Workstream overview</strong><span>Data</span><strong>Decisions + evidence</strong></div>' +
    '<nav class="main-nav">' +
      '<button type="button" class="tab-btn" data-mk-tab="gallery">Starting points</button>' +
      '<button type="button" class="tab-btn active" data-mk-tab="studio">Design</button>' +
      '<button type="button" class="tab-btn" data-mk-tab="import">Import</button>' +
      '<button type="button" class="tab-btn" data-mk-tab="tokens">Developer</button>' +
    '</nav>' +
    '<div class="view-mode-toggle" role="group" aria-label="CLI display mode">' +
      '<button type="button" class="toggle-btn active" data-mk-cli="split">Split</button>' +
      '<button type="button" class="toggle-btn" data-mk-cli="overlay">Overlay</button>' +
      '<button type="button" class="toggle-btn" data-mk-cli="hidden">Widgets only</button>' +
    '</div>' +
    '<section class="view-section hidden" data-mk-section="gallery">' +
      '<div class="examples-band">' +
        '<div class="examples-band-header">' +
          '<span class="eyebrow">Examples</span>' +
          '<span class="card-meta">Scroll or click</span>' +
        '</div>' +
        '<div class="examples-scroll" data-mk-examples-scroll></div>' +
      '</div>' +
      '<div class="gallery-grid" data-mk-gallery-grid></div>' +
    '</section>' +
    '<section class="view-section" data-mk-section="studio">' +
      '<div class="studio-container">' +
        '<div class="editor-pane">' +
          '<div class="editor-toolbar" style="flex-direction:column;align-items:stretch;gap:6px;">' +
            '<span class="eyebrow">What should this view help you notice?</span><span class="field-help">Describe an operator need. Cortxt keeps the view scoped to WS-042 and its authorized data.</span>' +
            '<textarea class="code-input studio-prompt" data-mk-studio-prompt spellcheck="false" placeholder="Show unresolved evidence gaps first, then the controls ready for acceptance."></textarea>' +
            '<div class="prompt-examples"><button type="button" data-prompt-example="Show unresolved evidence gaps first.">Evidence gaps</button><button type="button" data-prompt-example="Summarize decisions waiting for a person.">Pending decisions</button><button type="button" data-prompt-example="Show progress toward the accepted outcome.">Outcome progress</button></div>' +
            '<div style="display:flex;gap:6px;align-items:center;">' +
              '<button type="button" class="candidate-copy primary-action" data-mk-action="studio-generate">Create first draft</button>' +
              '<button type="button" class="candidate-copy hidden" data-mk-action="studio-confirm-install" data-mk-studio-confirm-btn disabled>Confirm &amp; install</button>' +
              '<span data-mk-studio-generate-status class="pulse-status"></span>' +
            '</div>' +
          '</div>' +
          '<div class="editor-toolbar">' +
            '<span class="eyebrow">View structure</span>' +
            '<select class="editor-select" data-mk-preset-select>' +
              '<option value="candidates">Candidates (GitHub)</option>' +
              '<option value="pulse">Session Pulse (Store)</option>' +
              '<option value="map">Execution Map (Plan)</option>' +
              '<option value="docker">Docker Status</option>' +
              '<option value="webhooks">Webhooks / Cloudflare</option>' +
              '<option value="usage">Usage &amp; Cost</option>' +
              '<option value="agents">Session Agents (Swimlanes)</option>' +
              '<option value="compliance">Compliance Audit (Custom)</option>' +
              '<option value="custom">Blank Spec</option>' +
            '</select>' +
          '</div>' +
          '<details class="advanced-editor"><summary>Developer details · specification and fixture data</summary><div class="editor-body">' +
            '<span class="eyebrow">Widget Spec (YAML)</span>' +
            '<textarea class="code-input" data-mk-studio-spec spellcheck="false"></textarea>' +
            '<span class="eyebrow" style="margin-top:4px;">Fixture Data (JSON)</span>' +
            '<textarea class="code-input" data-mk-studio-data spellcheck="false" style="min-height:90px;"></textarea>' +
            '<div style="display:flex;gap:6px;">' +
              '<button type="button" class="candidate-copy" data-mk-action="export-studio">Download .cw package</button>' +
              '<button type="button" class="candidate-copy" data-mk-action="rerender-studio">Validate &amp; preview</button>' +
            '</div>' +
          '</div></details>' +
        '</div>' +
        '<div class="editor-pane">' +
          '<div class="editor-toolbar">' +
            '<span class="eyebrow">Live preview</span>' +
            '<div class="status-ok" data-mk-studio-status>Valid</div>' +
          '</div>' +
          '<div class="card-body" style="flex:1;">' +
            '<div class="pane pane-render" data-mk-studio-render-pane></div>' +
            '<div class="pane pane-cli">' +
              '<div class="pane-title">' +
                '<span>Add to Work Console</span>' +
                '<button type="button" class="candidate-copy developer-only" data-mk-action="copy-studio-cmd">Copy command</button>' +
              '</div>' +
              '<p class="install-help">This preview shows where the view will live. Adding it is disabled because the public demo cannot change a workspace.</p><button type="button" class="studio-add" disabled>Add to Workstream overview</button><details class="developer-output"><summary>CLI installation</summary><div class="cli-cmd-box"><div class="cli-cmd" data-mk-studio-cmd-text>cortxt widget load --spec custom.yaml --view loaded</div></div></details>' +
              '<div class="pane-title developer-only" style="margin-top:4px;">' +
                '<span>CLI Render JSON</span>' +
                '<button type="button" class="candidate-copy" data-mk-action="copy-studio-json">Copy JSON</button>' +
              '</div>' +
              '<pre class="cli-json developer-only" data-mk-studio-json-text>{}</pre>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</section>' +
    '<section class="view-section hidden" data-mk-section="tokens">' +
      '<div class="studio-container">' +
        '<div class="editor-pane">' +
          '<div class="editor-toolbar">' +
            '<span class="eyebrow">Design Tokens (JSON)</span>' +
            '<span class="badge ok" data-mk-tokens-status-badge>applied</span>' +
            '<div style="display:flex;gap:6px;">' +
              '<button type="button" class="candidate-copy" data-mk-action="apply-tokens">Apply</button>' +
              '<button type="button" class="candidate-copy" data-mk-action="reset-tokens">Reset</button>' +
            '</div>' +
          '</div>' +
          '<div class="editor-body">' +
            '<textarea class="code-input" data-mk-tokens-input spellcheck="false" style="min-height:200px;"></textarea>' +
            '<div class="error-banner hidden" data-mk-tokens-error></div>' +
            '<div class="status-ok hidden" data-mk-tokens-success>Tokens valid and applied.</div>' +
          '</div>' +
        '</div>' +
        '<div class="editor-pane">' +
          '<div class="editor-toolbar"><span class="eyebrow">Live Preview</span></div>' +
          '<div class="editor-body" data-mk-tokens-preview style="background:#090c1580;"></div>' +
        '</div>' +
      '</div>' +
    '</section>' +
    '<section class="view-section hidden" data-mk-section="import">' +
      '<div class="card">' +
        '<div class="card-header">' +
          '<div class="card-title-group"><span class="card-title">Import Widget Package</span><span class="card-meta">.cw / JSON package</span></div>' +
          '<span class="badge" data-mk-import-badge>idle</span>' +
        '</div>' +
        '<div class="editor-body">' +
          '<label class="candidate-copy import-file-label">Choose .cw file<input type="file" data-mk-import-file accept=".cw,.json" style="display:none;"></label>' +
          '<textarea class="code-input" data-mk-import-textarea placeholder="Paste .cw package JSON content here..." style="min-height:110px;"></textarea>' +
          '<div style="display:flex;gap:8px;">' +
            '<button type="button" class="candidate-copy" data-mk-action="validate-import">Validate &amp; Preview</button>' +
            '<button type="button" class="candidate-copy" data-mk-action="clear-import">Clear</button>' +
          '</div>' +
          '<div class="error-banner hidden" data-mk-import-error></div>' +
          '<div class="hidden" data-mk-import-preview style="display:flex;flex-direction:column;gap:10px;border-top:1px solid var(--stroke);padding-top:10px;">' +
            '<div class="pane-title"><span>Live Preview</span><span class="card-meta" data-mk-import-meta></span></div>' +
            '<div class="pane pane-render" data-mk-import-render-pane style="min-height:100px;"></div>' +
            '<div class="pane-title" style="margin-top:6px;"><span>Install Command</span><button type="button" class="candidate-copy" data-mk-action="copy-import-cmd">Copy command</button></div>' +
            '<div class="cli-cmd-box"><div class="cli-cmd" data-mk-import-cli-cmd>cortxt widget load --package widget.cw</div></div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</section>';

  function mount(container) {
    if (!container) return;
    container.classList.add("maker-pane");
    container.innerHTML = MAKER_HTML;

    var q = function (sel) { return container.querySelector(sel); };
    var qa = function (sel) { return Array.prototype.slice.call(container.querySelectorAll(sel)); };

    var studioCliCmd = "cortxt widget load --spec custom.yaml --view loaded";
    var currentTokens = defaultTokens();
    var lastGoodTokens = defaultTokens();
    var tokensDebounce = null;
    var studioDebounce = null;
    var lastImportFileName = "widget.cw";
    var studioGenState = "draft"; // draft | generated | validation_failed | needs_scaffold | valid | confirmed | installed
    var studioGenOutcome = null; // raw generate_widget_spec-shaped response from api/widget-generate
    var studioGenScaffoldUsed = false; // sticky across a needs_scaffold -> valid transition, until the next prompt

    function escapeHtml(str) {
      return (str || "").toString()
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function copyText(text, btn) {
      var done = function () {
        var orig = btn.textContent;
        btn.textContent = "Copied!";
        btn.classList.add("copied");
        setTimeout(function () { btn.textContent = orig; btn.classList.remove("copied"); }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(done);
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.append(ta);
        ta.select();
        try { document.execCommand("copy"); } catch (e) {}
        ta.remove();
        done();
      }
    }

    function switchMode(mode) {
      qa("[data-mk-tab]").forEach(function (b) { b.classList.toggle("active", b.dataset.mkTab === mode); });
      qa("[data-mk-section]").forEach(function (s) { s.classList.toggle("hidden", s.dataset.mkSection !== mode); });
    }

    var CLI_MODE_KEY = "cortxt-cli-mode";
    var cliMode = (function () {
      try { return localStorage.getItem(CLI_MODE_KEY) || "split"; } catch (e) { return "split"; }
    })();

    function setCliMode(mode) {
      cliMode = mode;
      try { localStorage.setItem(CLI_MODE_KEY, mode); } catch (e) {}
      qa("[data-mk-cli]").forEach(function (b) { b.classList.toggle("active", b.dataset.mkCli === mode); });
      container.classList.toggle("cli-split", mode === "split");
      container.classList.toggle("cli-overlay", mode === "overlay");
      container.classList.toggle("cli-hidden", mode === "hidden");
    }

    async function initTokens() {
      try {
        var resp = await fetch("tokens.json", { cache: "no-store" });
        if (resp.ok) {
          var json = await resp.json();
          currentTokens = json;
          lastGoodTokens = JSON.parse(JSON.stringify(json));
          applyTokens(currentTokens);
        }
      } catch (e) {
        currentTokens = defaultTokens();
        lastGoodTokens = defaultTokens();
        applyTokens(currentTokens);
      }
      populateTokensEditor();
      renderTokensPreview();
    }

    function populateTokensEditor() {
      var input = q("[data-mk-tokens-input]");
      if (input) input.value = JSON.stringify(currentTokens, null, 2);
    }

    function handleTokensInput() {
      clearTimeout(tokensDebounce);
      tokensDebounce = setTimeout(applyEditedTokens, 150);
    }

    function applyEditedTokens() {
      var input = q("[data-mk-tokens-input]");
      var errLine = q("[data-mk-tokens-error]");
      var succLine = q("[data-mk-tokens-success]");
      var statusBadge = q("[data-mk-tokens-status-badge]");
      if (!input) return;

      var raw = input.value.trim();
      var parsed = null;
      try {
        parsed = JSON.parse(raw);
      } catch (e) {
        if (errLine) { errLine.textContent = "Malformed JSON: " + e.message; errLine.classList.remove("hidden"); }
        if (succLine) succLine.classList.add("hidden");
        if (statusBadge) { statusBadge.className = "badge err"; statusBadge.textContent = "error"; }
        return;
      }

      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        if (errLine) { errLine.textContent = "Tokens must be a JSON object."; errLine.classList.remove("hidden"); }
        if (succLine) succLine.classList.add("hidden");
        if (statusBadge) { statusBadge.className = "badge err"; statusBadge.textContent = "invalid"; }
        return;
      }

      var requiredSections = ["colors", "typography", "spacing", "radius", "density"];
      var missing = requiredSections.filter(function (s) { return !parsed[s] || typeof parsed[s] !== "object"; });
      if (missing.length > 0) {
        if (errLine) { errLine.textContent = "Missing required token sections: " + missing.join(", "); errLine.classList.remove("hidden"); }
        if (succLine) succLine.classList.add("hidden");
        if (statusBadge) { statusBadge.className = "badge err"; statusBadge.textContent = "invalid"; }
        return;
      }

      currentTokens = parsed;
      lastGoodTokens = JSON.parse(JSON.stringify(parsed));
      applyTokens(currentTokens);

      if (errLine) errLine.classList.add("hidden");
      if (succLine) { succLine.textContent = "Tokens valid and applied."; succLine.classList.remove("hidden"); }
      if (statusBadge) { statusBadge.className = "badge ok"; statusBadge.textContent = "applied"; }

      renderTokensPreview();
    }

    function resetTokensToDefaults() {
      currentTokens = defaultTokens();
      lastGoodTokens = defaultTokens();
      applyTokens(currentTokens);
      populateTokensEditor();

      var errLine = q("[data-mk-tokens-error]");
      var succLine = q("[data-mk-tokens-success]");
      var statusBadge = q("[data-mk-tokens-status-badge]");
      if (errLine) errLine.classList.add("hidden");
      if (succLine) { succLine.textContent = "Reset to default tokens."; succLine.classList.remove("hidden"); }
      if (statusBadge) { statusBadge.className = "badge ok"; statusBadge.textContent = "defaults"; }

      renderTokensPreview();
    }

    function renderTokensPreview() {
      var pane = q("[data-mk-tokens-preview]");
      if (!pane) return;
      pane.replaceChildren();

      var colors = currentTokens.colors || {};
      var colorSec = document.createElement("div");
      colorSec.className = "candidate-group";
      var colorHead = document.createElement("h3");
      colorHead.textContent = "Color Palette";
      colorSec.append(colorHead);

      var grid = document.createElement("div");
      grid.className = "token-grid";
      Object.keys(colors).forEach(function (k) {
        var chip = document.createElement("div");
        chip.className = "token-chip";
        var swatch = document.createElement("div");
        swatch.className = "token-swatch";
        swatch.style.backgroundColor = colors[k];
        var lbl = document.createElement("span");
        lbl.className = "token-label";
        lbl.textContent = k + ": " + colors[k];
        chip.append(swatch, lbl);
        grid.append(chip);
      });
      colorSec.append(grid);
      pane.append(colorSec);

      var compSec = document.createElement("div");
      compSec.className = "candidate-group";
      compSec.style.marginTop = "10px";
      var compHead = document.createElement("h3");
      compHead.textContent = "Sample Elements";
      compSec.append(compHead);

      var stack = document.createElement("div");
      stack.className = "widget-stack";

      var badgeRow = document.createElement("div");
      badgeRow.className = "widget-row";
      badgeRow.innerHTML =
        '<span class="badge">accent</span>' +
        '<span class="badge ok">ok</span>' +
        '<span class="badge err">bad</span>' +
        '<span class="badge off">off</span>';
      stack.append(badgeRow);

      var stat = document.createElement("div");
      stat.className = "pulse-stat";
      stat.innerHTML = "<b>99.9%</b><span>Health SLA</span>";
      stack.append(stat);

      var statusBlock = document.createElement("div");
      statusBlock.className = "pulse-status";
      statusBlock.textContent = "Visual tokens active across host and CLI.";
      stack.append(statusBlock);

      compSec.append(stack);
      pane.append(compSec);
    }

    function renderExamplesBand(manifestList) {
      var scroll = q("[data-mk-examples-scroll]");
      if (!scroll) return;
      scroll.replaceChildren();

      manifestList.forEach(function (w) {
        var chip = document.createElement("div");
        chip.className = "example-chip";
        var isLive = ["session-agents", "usage", "pulse"].indexOf(w.id) !== -1;
        chip.innerHTML =
          '<div class="example-chip-title"><span>' + escapeHtml(w.title || w.id) + '</span>' +
          '<span class="badge ' + (isLive ? "ok pulse-dot" : "off") + '">' + (isLive ? "live" : "ready") + '</span></div>' +
          '<div class="example-chip-hint">' + escapeHtml(w.hint || "") + '</div>';
        chip.onclick = function () {
          var targetCard = q("#mk-card-" + w.id);
          if (targetCard) {
            targetCard.scrollIntoView({ behavior: "smooth", block: "center" });
            targetCard.style.outline = "2px solid var(--accent)";
            setTimeout(function () { targetCard.style.outline = "none"; }, 1500);
          }
        };
        scroll.append(chip);
      });
    }

    async function loadManifestAndRender() {
      var grid = q("[data-mk-gallery-grid]");
      grid.replaceChildren();

      var manifestList = [];
      try {
        var resp = await fetch("widgets.json", { cache: "no-store" });
        if (resp.ok) {
          var json = await resp.json();
          manifestList = json.widgets || [];
        }
      } catch (e) {}

      if (!manifestList.length) {
        manifestList = [
          { id: "candidates", title: "Candidates", spec: "widget_contract/specs/candidates-0.1.yaml", artifact: "candidates.json", hint: "cortxt widget --view candidates --repo OWNER/REPO" },
          { id: "pulse", title: "Pulse", spec: "widget_contract/specs/session-pulse-0.1.yaml", artifact: "session-pulse.json", hint: "cortxt widget --view session-pulse" },
          { id: "map", title: "Map", spec: "widget_contract/specs/execution-map-0.1.yaml", artifact: "execution-map.json", hint: "cortxt widget --view execution-map --plan-input <file>" },
          { id: "docker", title: "Docker", spec: "widget_contract/specs/docker-status-0.1.yaml", artifact: "docker-status.json", hint: "cortxt widget --view docker-status" },
          { id: "webhooks", title: "Webhooks", spec: "widget_contract/specs/webhooks-0.1.yaml", artifact: "webhooks.json", hint: "cortxt widget --view webhooks" },
          { id: "agents", title: "Agents", spec: "widget_contract/specs/session-agents-0.1.yaml", artifact: "session-agents.json", hint: "cortxt widget --view session-agents" },
          { id: "usage", title: "Usage & Cost", spec: "widget_contract/specs/usage-cost-0.1.yaml", artifact: "usage-cost.json", hint: "cortxt widget --view usage-cost" },
          { id: "loaded", title: "Loaded", spec: null, artifact: "loaded.json", hint: "cortxt widget load --spec <file> --view loaded" },
          { id: "composed", title: "Composed", spec: null, artifact: "composed.json", hint: "cortxt widget compose --spec <file> --widgets-dir <dir>" }
        ];
      }

      renderExamplesBand(manifestList);

      manifestList.forEach(function (w) {
        var card = document.createElement("div");
        card.className = "card";
        card.id = "mk-card-" + w.id;

        var header = document.createElement("div");
        header.className = "card-header";
        header.innerHTML =
          '<div class="card-title-group"><span class="card-title">' + escapeHtml(w.title || w.id) + '</span>' +
          '<span class="card-meta">' + escapeHtml(w.id) + ' &bull; ' + (w.spec ? escapeHtml(w.spec) : "dynamic spec") + '</span></div>' +
          '<span class="badge ok" id="mk-badge-' + w.id + '">ready</span>';
        card.append(header);

        var body = document.createElement("div");
        body.className = "card-body";

        var renderPane = document.createElement("div");
        renderPane.className = "pane pane-render";

        var cliPane = document.createElement("div");
        cliPane.className = "pane pane-cli";

        var cmdTitle = document.createElement("div");
        cmdTitle.className = "pane-title";
        cmdTitle.innerHTML = "<span>CLI Command</span>";
        var copyCmdBtn = document.createElement("button");
        copyCmdBtn.type = "button";
        copyCmdBtn.className = "candidate-copy";
        copyCmdBtn.textContent = "Copy";
        copyCmdBtn.onclick = function () { copyText(w.hint || "", copyCmdBtn); };

        var exportBtn = document.createElement("button");
        exportBtn.type = "button";
        exportBtn.className = "candidate-copy";
        exportBtn.textContent = "Export";
        exportBtn.onclick = function () { exportWidgetPackage(w, exportBtn); };

        var btnGroup = document.createElement("div");
        btnGroup.style.display = "flex";
        btnGroup.style.gap = "6px";
        btnGroup.append(copyCmdBtn, exportBtn);
        cmdTitle.append(btnGroup);

        var cmdBox = document.createElement("div");
        cmdBox.className = "cli-cmd-box";
        cmdBox.innerHTML = '<div class="cli-cmd">' + escapeHtml(w.hint || "") + '</div>';

        var jsonTitle = document.createElement("div");
        jsonTitle.className = "pane-title";
        jsonTitle.style.marginTop = "4px";
        jsonTitle.innerHTML = "<span>CLI Output JSON</span>";
        var copyJsonBtn = document.createElement("button");
        copyJsonBtn.type = "button";
        copyJsonBtn.className = "candidate-copy";
        copyJsonBtn.textContent = "Copy";

        var jsonPre = document.createElement("pre");
        jsonPre.className = "cli-json";
        jsonPre.textContent = "Loading...";

        copyJsonBtn.onclick = function () { copyText(jsonPre.textContent, copyJsonBtn); };
        jsonTitle.append(copyJsonBtn);

        cliPane.append(cmdTitle, cmdBox, jsonTitle, jsonPre);
        body.append(renderPane, cliPane);
        card.append(body);
        grid.append(card);

        loadWidgetArtifact(w, renderPane, jsonPre, q("#mk-badge-" + w.id));
      });
    }

    async function loadWidgetArtifact(w, renderPane, jsonPre, badge) {
      var artifact = null;
      try {
        var resp = await fetch(w.artifact, { cache: "no-store" });
        if (resp.ok) artifact = await resp.json();
      } catch (e) {}

      if (!artifact && PRESETS[w.id]) {
        var p = PRESETS[w.id];
        var parsed = parseYamlSubset(p.spec);
        if (parsed.ok) artifact = renderSpec(parsed.data, p.data);
      }

      renderPane.replaceChildren();
      if (artifact) {
        var renderTree = artifact.render || artifact;
        renderNodeToDom(renderTree, renderPane);
        jsonPre.textContent = formatCliOutput(artifact);
        if (badge) {
          var state = renderTree.state || "ok";
          badge.className = "badge " + (state === "error" ? "err" : "ok");
          badge.textContent = state;
        }
      } else {
        renderPane.innerHTML = '<div class="empty">No artifact. Run <code>' + escapeHtml(w.hint || "") + '</code> to build.</div>';
        jsonPre.textContent = "{}";
        if (badge) { badge.className = "badge off"; badge.textContent = "offline"; }
      }
    }

    function loadPreset(key) {
      var p = PRESETS[key] || PRESETS.custom;
      q("[data-mk-preset-select]").value = key;
      q("[data-mk-studio-spec]").value = p.spec;
      q("[data-mk-studio-data]").value = JSON.stringify(p.data || {}, null, 2);
      studioCliCmd = p.hint || ("cortxt widget load --spec " + key + ".yaml --view loaded");
      q("[data-mk-studio-cmd-text]").textContent = studioCliCmd;
      reRenderStudio();
    }

    function handleStudioInput() {
      clearTimeout(studioDebounce);
      studioDebounce = setTimeout(reRenderStudio, 150);
    }

    function reRenderStudio() {
      var specText = q("[data-mk-studio-spec]").value;
      var dataText = q("[data-mk-studio-data]").value;
      var renderPane = q("[data-mk-studio-render-pane]");
      var statusNode = q("[data-mk-studio-status]");
      var jsonText = q("[data-mk-studio-json-text]");

      renderPane.replaceChildren();

      var parsedYaml = parseYamlSubset(specText);
      if (!parsedYaml.ok) {
        statusNode.className = "error-banner";
        statusNode.textContent = "YAML Error: " + parsedYaml.error;
        renderPane.innerHTML = '<div class="pulse-status error">Failed to parse YAML spec: ' + escapeHtml(parsedYaml.error) + '</div>';
        jsonText.textContent = "{}";
        return;
      }

      var fixtureData = {};
      if (dataText.trim()) {
        try {
          fixtureData = JSON.parse(dataText);
        } catch (err) {
          statusNode.className = "error-banner";
          statusNode.textContent = "JSON Data Error: " + err.message;
          renderPane.innerHTML = '<div class="pulse-status error">Malformed JSON fixture data: ' + escapeHtml(err.message) + '</div>';
          jsonText.textContent = "{}";
          return;
        }
      }

      try {
        var renderedArtifact = renderSpec(parsedYaml.data, fixtureData);
        statusNode.className = "status-ok";
        statusNode.textContent = "Valid";
        renderNodeToDom(renderedArtifact.render, renderPane);
        jsonText.textContent = formatCliOutput(renderedArtifact);
      } catch (err) {
        statusNode.className = "error-banner";
        statusNode.textContent = "Render Error: " + err.message;
        renderPane.innerHTML = '<div class="pulse-status error">Spec render failed: ' + escapeHtml(err.message) + '</div>';
        jsonText.textContent = "{}";
      }
    }

    function renderStudioGenerateStatus() {
      var statusEl = q("[data-mk-studio-generate-status]");
      var confirmBtn = q("[data-mk-studio-confirm-btn]");
      if (!statusEl || !confirmBtn) return;
      var labels = {
        draft: "", generated: "Generating…",
        validation_failed: "Not valid: " + ((studioGenOutcome && studioGenOutcome.error_message) || "generation failed"),
        needs_scaffold: "Missing read operation(s): " + ((studioGenOutcome && studioGenOutcome.missing_operations || []).join(", ")) +
          " — scaffold written to " + ((studioGenOutcome && studioGenOutcome.scaffold_paths || []).join(", ")),
        valid: "Valid — " + (studioGenOutcome ? studioGenOutcome.widget_id + " v" + studioGenOutcome.widget_version : ""),
        installed: "Installed" + (studioGenScaffoldUsed ? " — representative data, scaffolded read" : ""),
      };
      statusEl.textContent = labels[studioGenState] || "";
      confirmBtn.classList.toggle("hidden", !(studioGenState === "valid" || studioGenState === "installed"));
      confirmBtn.disabled = studioGenState !== "valid";
      confirmBtn.textContent = studioGenState === "installed" ? "Installed" : "Confirm & install";
    }

    function studioGenerate() {
      var promptEl = q("[data-mk-studio-prompt]");
      var prompt = promptEl ? promptEl.value.trim() : "";
      if (!prompt) return;
      studioGenState = "generated";
      studioGenOutcome = null;
      studioGenScaffoldUsed = false;
      renderStudioGenerateStatus();
      fetch("api/widget-generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt, confirm: false }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          studioGenOutcome = data;
          studioGenState = { ok: "valid", missing_operation: "needs_scaffold", invalid: "validation_failed" }[data.status] || "validation_failed";
          if (studioGenState === "needs_scaffold") studioGenScaffoldUsed = true;
          renderStudioGenerateStatus();
          if (studioGenState === "valid" && data.spec_text) {
            q("[data-mk-studio-spec]").value = data.spec_text;
            reRenderStudio();
          }
        })
        .catch(function (err) {
          studioGenOutcome = { error_message: err.message || "request failed" };
          studioGenState = "validation_failed";
          renderStudioGenerateStatus();
        });
    }

    function studioConfirmInstall() {
      if (studioGenState !== "valid") return; // defense in depth; the button is also disabled
      var promptEl = q("[data-mk-studio-prompt]");
      var prompt = promptEl ? promptEl.value.trim() : "";
      fetch("api/widget-generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt, confirm: true }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.status !== "succeeded") {
            studioGenState = "validation_failed";
            studioGenOutcome = data.error || data;
            renderStudioGenerateStatus();
            return;
          }
          studioGenState = "installed";
          renderStudioGenerateStatus();
        })
        .catch(function (err) {
          studioGenOutcome = { error_message: err.message || "request failed" };
          studioGenState = "validation_failed";
          renderStudioGenerateStatus();
        });
    }

    var SECRET_PATTERNS = [
      /sk-[a-zA-Z0-9_-]{10,}/,
      /cfat_[a-zA-Z0-9_-]{10,}/,
      /ghp_[a-zA-Z0-9_-]{10,}/,
      /github_pat_[a-zA-Z0-9_-]{10,}/,
      /-----BEGIN\s+[A-Z\s]+KEY-----/
    ];

    function containsSecretsClient(val) {
      if (!val) return false;
      var str = typeof val === "string" ? val : JSON.stringify(val);
      for (var i = 0; i < SECRET_PATTERNS.length; i++) {
        if (SECRET_PATTERNS[i].test(str)) return true;
      }
      return false;
    }

    async function getRendererSource() {
      try {
        var resp = await fetch("maker.js");
        if (resp.ok) return await resp.text();
      } catch (e) {}
      return "// Cortxt Widget Maker renderer";
    }

    async function exportWidgetPackage(w, btn) {
      var originalText = btn ? btn.textContent : "";
      if (btn) btn.textContent = "Exporting...";
      try {
        var specText = "";
        if (w.spec) {
          try {
            var resp = await fetch(w.spec);
            if (resp.ok) specText = await resp.text();
          } catch (e) {}
        }
        if (!specText && PRESETS[w.id]) specText = PRESETS[w.id].spec;
        if (!specText) { alert("Could not load spec for " + w.id); return; }

        var artifactObj = null;
        if (w.artifact) {
          try {
            var resp2 = await fetch(w.artifact);
            if (resp2.ok) artifactObj = await resp2.json();
          } catch (e) {}
        }
        if (!artifactObj && PRESETS[w.id]) {
          var p = PRESETS[w.id];
          var parsed = parseYamlSubset(p.spec);
          if (parsed.ok) artifactObj = renderSpec(parsed.data, p.data);
        }

        var rendererSrc = await getRendererSource();
        var tokensObj = currentTokens || defaultTokens();

        var pkg = {
          package_format: "1",
          manifest: {
            package_format_version: "1",
            widget_id: w.id,
            widget_version: "0.1",
            title: w.title || w.id,
            exported_at: new Date().toISOString(),
            tokens_version: "visual-tokens.v1"
          },
          widget: specText,
          tokens: tokensObj,
          renderer: rendererSrc
        };
        if (artifactObj) pkg.fixture = artifactObj;

        if (containsSecretsClient(pkg)) { alert("Export aborted: secret-shaped pattern detected in widget content."); return; }

        var blob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = (w.id || "widget") + ".cw";
        document.body.append(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } finally {
        if (btn) btn.textContent = originalText;
      }
    }

    async function exportStudioWidget() {
      var specText = q("[data-mk-studio-spec]").value;
      var dataText = q("[data-mk-studio-data]").value;
      var parsedYaml = parseYamlSubset(specText);
      if (!parsedYaml.ok) { alert("Cannot export: Spec YAML is invalid."); return; }
      var fixtureData = {};
      try {
        if (dataText.trim()) fixtureData = JSON.parse(dataText);
      } catch (e) { alert("Cannot export: Fixture JSON is invalid."); return; }

      var widgetId = (parsedYaml.data && parsedYaml.data.widget && parsedYaml.data.widget.id) || "custom";
      var widgetVersion = (parsedYaml.data && parsedYaml.data.widget && parsedYaml.data.widget.version) || "0.1";
      var widgetTitle = (parsedYaml.data && parsedYaml.data.widget && parsedYaml.data.widget.title) || "Custom Widget";
      var renderedArtifact = renderSpec(parsedYaml.data, fixtureData);
      var rendererSrc = await getRendererSource();
      var tokensObj = currentTokens || defaultTokens();

      var pkg = {
        package_format: "1",
        manifest: {
          package_format_version: "1",
          widget_id: widgetId,
          widget_version: widgetVersion,
          title: widgetTitle,
          exported_at: new Date().toISOString(),
          tokens_version: "visual-tokens.v1"
        },
        widget: specText,
        tokens: tokensObj,
        renderer: rendererSrc,
        fixture: renderedArtifact
      };

      if (containsSecretsClient(pkg)) { alert("Export aborted: secret-shaped pattern detected."); return; }

      var blob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = widgetId + ".cw";
      document.body.append(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }

    function handleImportFile(event) {
      var file = event.target.files && event.target.files[0];
      if (!file) return;
      lastImportFileName = file.name;
      var reader = new FileReader();
      reader.onload = function (e) {
        q("[data-mk-import-textarea]").value = e.target.result;
        validateAndPreviewImport();
      };
      reader.readAsText(file);
    }

    function handleImportTextChange() {
      var errLine = q("[data-mk-import-error]");
      if (errLine) { errLine.classList.add("hidden"); errLine.textContent = ""; }
    }

    function clearImport() {
      q("[data-mk-import-textarea]").value = "";
      q("[data-mk-import-file]").value = "";
      var errLine = q("[data-mk-import-error]");
      errLine.classList.add("hidden");
      errLine.textContent = "";
      q("[data-mk-import-preview]").classList.add("hidden");
      var badge = q("[data-mk-import-badge]");
      badge.className = "badge";
      badge.textContent = "idle";
    }

    function validateAndPreviewImport() {
      var text = q("[data-mk-import-textarea]").value.trim();
      var errLine = q("[data-mk-import-error]");
      var preview = q("[data-mk-import-preview]");
      var renderPane = q("[data-mk-import-render-pane]");
      var metaInfo = q("[data-mk-import-meta]");
      var cliCmd = q("[data-mk-import-cli-cmd]");
      var badge = q("[data-mk-import-badge]");

      errLine.classList.add("hidden");
      errLine.textContent = "";
      preview.classList.add("hidden");
      renderPane.replaceChildren();

      if (!text) {
        errLine.textContent = "Please paste a package JSON or upload a .cw file.";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "empty";
        return;
      }

      var pkg = null;
      try {
        pkg = JSON.parse(text);
      } catch (e) {
        errLine.textContent = "Malformed JSON: " + e.message;
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "invalid json";
        return;
      }

      if (typeof pkg !== "object" || pkg === null || Array.isArray(pkg)) {
        errLine.textContent = "Package must be a JSON object.";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "invalid";
        return;
      }

      var fmt = pkg.package_format || (pkg.manifest && pkg.manifest.package_format_version);
      if (fmt !== "1") {
        errLine.textContent = "Unsupported package format version: '" + fmt + "' (expected '1').";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "unsupported format";
        return;
      }

      if (!pkg.widget || typeof pkg.widget !== "string") {
        errLine.textContent = "Missing required 'widget' spec string.";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "missing spec";
        return;
      }

      if (!pkg.tokens || typeof pkg.tokens !== "object") {
        errLine.textContent = "Missing required 'tokens' object.";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "missing tokens";
        return;
      }

      if (!pkg.renderer || typeof pkg.renderer !== "string") {
        errLine.textContent = "Missing required 'renderer' string.";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "missing renderer";
        return;
      }

      if (containsSecretsClient(pkg)) {
        errLine.textContent = "Package rejected: secret-shaped content detected.";
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "secrets detected";
        return;
      }

      var parsed = parseYamlSubset(pkg.widget);
      if (!parsed.ok) {
        errLine.textContent = "Invalid widget contract YAML: " + parsed.error;
        errLine.classList.remove("hidden");
        badge.className = "badge err"; badge.textContent = "spec error";
        return;
      }

      var widgetId = (parsed.data && parsed.data.widget && parsed.data.widget.id) || (pkg.manifest && pkg.manifest.widget_id) || "widget";
      var widgetVersion = (parsed.data && parsed.data.widget && parsed.data.widget.version) || (pkg.manifest && pkg.manifest.widget_version) || "0.1";
      var widgetTitle = (parsed.data && parsed.data.widget && parsed.data.widget.title) || (pkg.manifest && pkg.manifest.title) || widgetId;

      applyTokens(pkg.tokens);

      var renderTree = null;
      if (pkg.fixture) {
        renderTree = pkg.fixture.render || pkg.fixture;
      } else {
        renderTree = renderSpec(parsed.data, {}).render;
      }

      renderNodeToDom(renderTree, renderPane);

      var expAt = pkg.manifest && pkg.manifest.exported_at ? " &bull; exported: " + escapeHtml(pkg.manifest.exported_at) : "";
      metaInfo.innerHTML = "id: <strong>" + escapeHtml(widgetId) + "</strong> &bull; version: " + escapeHtml(widgetVersion) + " &bull; title: " + escapeHtml(widgetTitle) + expAt;
      cliCmd.textContent = "cortxt widget load --package " + lastImportFileName;

      preview.classList.remove("hidden");
      badge.className = "badge ok"; badge.textContent = "valid package";
    }

    // Wire up all static controls (dynamically-built gallery/preset elements
    // above set their own .onclick directly since they close over per-item
    // data).
    qa("[data-mk-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () { switchMode(btn.dataset.mkTab); });
    });
    qa("[data-mk-cli]").forEach(function (btn) {
      btn.addEventListener("click", function () { setCliMode(btn.dataset.mkCli); });
    });
    q("[data-mk-preset-select]").addEventListener("change", function (ev) { loadPreset(ev.target.value); });
    q("[data-mk-studio-spec]").addEventListener("input", handleStudioInput);
    q("[data-mk-studio-data]").addEventListener("input", handleStudioInput);
    qa("[data-prompt-example]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        q("[data-mk-studio-prompt]").value = btn.dataset.promptExample;
      });
    });
    q("[data-mk-tokens-input]").addEventListener("input", handleTokensInput);
    q("[data-mk-import-file]").addEventListener("change", handleImportFile);
    q("[data-mk-import-textarea]").addEventListener("input", handleImportTextChange);

    container.addEventListener("click", function (ev) {
      var el = ev.target.closest("[data-mk-action]");
      if (!el) return;
      var action = el.dataset.mkAction;
      if (action === "export-studio") exportStudioWidget();
      else if (action === "rerender-studio") reRenderStudio();
      else if (action === "studio-generate") studioGenerate();
      else if (action === "studio-confirm-install") studioConfirmInstall();
      else if (action === "copy-studio-cmd") copyText(studioCliCmd, el);
      else if (action === "copy-studio-json") copyText(q("[data-mk-studio-json-text]").textContent, el);
      else if (action === "apply-tokens") applyEditedTokens();
      else if (action === "reset-tokens") resetTokensToDefaults();
      else if (action === "validate-import") validateAndPreviewImport();
      else if (action === "clear-import") clearImport();
      else if (action === "copy-import-cmd") copyText(q("[data-mk-import-cli-cmd]").textContent, el);
    });

    initTokens();
    loadManifestAndRender();
    loadPreset("compliance");
    setCliMode(cliMode);
    switchMode("studio");
    var workstreamParam = new URLSearchParams(window.location.search).get("workstream");
    var globalContext = document.getElementById("gbar-context");
    if (workstreamParam && globalContext) globalContext.textContent = workstreamParam + " · Workstream overview";
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
    pickReadableTextColor: pickReadableTextColor,
    createSequenceStepper: createSequenceStepper,
    startLivingDemo: startLivingDemo,
    mount: mount,
  };
});
