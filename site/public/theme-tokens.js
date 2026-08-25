/*
 * Applies the resolved visual-tokens document to every page's :root as
 * `--token-<name>` CSS custom properties (issue #376: landing + docs must
 * consume the same semantic token keys as the widget host, not invent
 * their own palette). `widgets/tokens.json` is the mechanically generated
 * copy of `agent-platform/widget/tokens.json` (scripts/generate_widget_tokens.py,
 * issue #373) -- whatever preset `cortxt widget`/`cortxt theme use` last
 * resolved into that source file flows through unchanged. `landing.css`
 * and `custom.css` reference `var(--token-<name>, <fallback-hex>)`, so a
 * failed or slow fetch never leaves the page unstyled -- it just falls
 * back to the quiet-slate-shaped defaults baked into the stylesheets,
 * exactly like the widget host's own DEFAULT_FALLBACK_TOKENS pattern.
 */
(function () {
  // WCAG relative luminance / contrast helpers, mirrored from
  // agent-platform/widget/maker.js's pickReadableTextColor (issue #376
  // review finding 2): the Atlas logo mark sits on a
  // linear-gradient(--atlas-accent, --atlas-accent-2) fill, and no single
  // literal text color clears 4.5:1 against every preset -- the shipped
  // default palette's accent is dark/saturated (wants light text) while
  // the visual-tokens.v2 presets' accent is pastel/lighter (wants dark
  // text). Picking at runtime from the actually-resolved colors avoids
  // hardcoding a color that regresses for one regime or the other.
  function hexToRgb(hex) {
    if (typeof hex !== "string") return null;
    var v = hex.trim();
    if (v[0] !== "#") return null;
    v = v.slice(1);
    if (v.length === 4 || v.length === 8) v = v.slice(0, v.length === 4 ? 3 : 6);
    if (v.length === 3) v = v.split("").map(function (ch) { return ch + ch; }).join("");
    if (v.length !== 6) return null;
    var num = parseInt(v, 16);
    if (isNaN(num)) return null;
    return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
  }

  function srgbChannelToLinear(channel) {
    var c = channel / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  function relativeLuminance(hex) {
    var rgb = hexToRgb(hex);
    if (!rgb) return null;
    return 0.2126 * srgbChannelToLinear(rgb.r) + 0.7152 * srgbChannelToLinear(rgb.g) + 0.0722 * srgbChannelToLinear(rgb.b);
  }

  function contrastRatio(hexA, hexB) {
    var la = relativeLuminance(hexA);
    var lb = relativeLuminance(hexB);
    if (la === null || lb === null) return null;
    var lighter = Math.max(la, lb);
    var darker = Math.min(la, lb);
    return (lighter + 0.05) / (darker + 0.05);
  }

  // `--atlas-accent` is `color-mix(in srgb, accent 70%, white 30%)`
  // (atlas.css) -- approximate that per-channel blend here so the picker
  // sees the same gradient stop the browser actually paints.
  function mixWithWhite(hex, accentFraction) {
    var rgb = hexToRgb(hex);
    if (!rgb) return hex;
    var mix = function (channel) {
      return Math.round(channel * accentFraction + 255 * (1 - accentFraction));
    };
    var toHex = function (n) { return n.toString(16).padStart(2, "0"); };
    return "#" + toHex(mix(rgb.r)) + toHex(mix(rgb.g)) + toHex(mix(rgb.b));
  }

  function pickReadableTextColor(hexColors) {
    var candidates = ["#000000", "#ffffff"];
    var best = "#ffffff";
    var bestScore = -1;
    candidates.forEach(function (candidate) {
      var minRatio = Infinity;
      var any = false;
      hexColors.forEach(function (bg) {
        var ratio = contrastRatio(candidate, bg);
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

  function applyTokens(tokens) {
    var root = document.documentElement;
    if (!root || !tokens || typeof tokens !== "object") return;
    var colors = tokens.colors || {};
    Object.keys(colors).forEach(function (name) {
      var value = colors[name];
      if (typeof value === "string") {
        root.style.setProperty("--token-" + name, value);
      }
    });
    if (typeof colors.accent === "string") {
      var atlasAccent = mixWithWhite(colors.accent, 0.7);
      root.style.setProperty("--atlas-on-accent", pickReadableTextColor([atlasAccent, colors.accent]));
    }
  }

  fetch("/widgets/tokens.json", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    })
    .then(applyTokens)
    .catch(function () {
      /* Fall through to the stylesheets' own var() fallbacks. */
    });
})();
