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
          current += c;
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

  return {
    resolvePointer: resolvePointer,
    parseYamlSubset: parseYamlSubset,
    renderSpec: renderSpec,
    renderNodeToDom: renderNodeToDom,
    formatCliOutput: formatCliOutput,
  };
});
