/*
 * Issue #377: the public landing page renders a fixed default preset
 * (quiet-slate) for every visitor -- unlike every other page, it does NOT
 * fetch the server-resolved /widgets/tokens.json (that reflects whatever
 * preset an operator last set via `cortxt theme use`, and mixing the two
 * would make the "fixed default" promise a lie for some visitors). Instead
 * this script applies quiet-slate's colors directly, then offers a
 * client-side, localStorage-only toggle across all three shipped presets.
 * Nothing here is persisted server-side; a visitor's choice lives only in
 * this browser (agent-platform/widget/presets/visual-tokens.v2.json is the
 * source of truth these color values are copied from -- kept in sync by
 * hand since this static file has no build step to import Python/JSON).
 */
(function () {
  var STORAGE_KEY = "cortxt-landing-preset";
  var DEFAULT_PRESET = "quiet-slate";

  var PRESETS = {
    "quiet-slate": {
      background: "#101216", surface: "#181b20", layer: "#ffffff0d", hover: "#ffffff15",
      stroke: "#5b6471", strong: "#727c8a", text: "#e7ebf0", muted: "#8d97a3", dim: "#65717f",
      accent: "#8fa3c7", blue: "#7885a7", ok: "#a8d5ba", warn: "#d8c49a", bad: "#d9a6b2",
    },
    "graphite-ink": {
      background: "#101112", surface: "#181a1c", layer: "#ffffff0d", hover: "#ffffff15",
      stroke: "#606368", strong: "#777b81", text: "#e8e9e9", muted: "#909397", dim: "#686d73",
      accent: "#8aa2ba", blue: "#73849a", ok: "#8fb89a", warn: "#c6b580", bad: "#c98f96",
    },
    "soft-dusk": {
      background: "#12131a", surface: "#1a1c25", layer: "#ffffff0d", hover: "#ffffff15",
      stroke: "#5f6375", strong: "#767b8e", text: "#ececf1", muted: "#9699a9", dim: "#6e7385",
      accent: "#9a9dc8", blue: "#837fa8", ok: "#abd2bd", warn: "#d9c69d", bad: "#d7a8bd",
    },
  };

  function applyPreset(id) {
    var colors = PRESETS[id] || PRESETS[DEFAULT_PRESET];
    var root = document.documentElement;
    if (!root) return;
    Object.keys(colors).forEach(function (name) {
      root.style.setProperty("--token-" + name, colors[name]);
    });
  }

  function readStoredPreset() {
    try {
      var stored = window.localStorage.getItem(STORAGE_KEY);
      return stored && PRESETS[stored] ? stored : DEFAULT_PRESET;
    } catch (e) {
      return DEFAULT_PRESET;
    }
  }

  function storePreset(id) {
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch (e) {
      /* localStorage unavailable (private mode, disabled) -- the toggle
         still works for this page view, it just won't persist. */
    }
  }

  var active = readStoredPreset();
  applyPreset(active);

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    var buttons = toggle.querySelectorAll("button[data-preset]");
    buttons.forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-preset") === active);
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-preset");
        if (!PRESETS[id]) return;
        active = id;
        applyPreset(id);
        storePreset(id);
        buttons.forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
      });
    });
  });
})();
