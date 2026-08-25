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
