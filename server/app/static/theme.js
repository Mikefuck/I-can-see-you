/* Run before the stylesheet so a remembered dark theme never starts with a white page. */
(() => {
  "use strict";
  const key = "focus-ledger.theme";
  const labels = { system: "跟随系统", light: "浅色", dark: "深色" };
  const normalize = value => Object.hasOwn(labels, value) ? value : "system";
  const system = matchMedia("(prefers-color-scheme: dark)");
  let preference = "system";
  try { preference = normalize(localStorage.getItem(key)); } catch (_) { /* Storage can be disabled. */ }

  function apply() {
    const theme = preference === "system" ? (system.matches ? "dark" : "light") : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themePreference = preference;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#161616" : "#ffffff";
    document.querySelectorAll("[data-theme-label]").forEach(node => { node.textContent = labels[preference]; });
    document.querySelectorAll("[data-theme-option]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.themeOption === preference));
    });
    const summary = document.querySelector("[data-theme-picker] summary");
    if (summary) {
      const description = `切换主题，当前${labels[preference]}（${labels[theme]}）`;
      summary.setAttribute("aria-label", description);
      summary.title = description;
    }
  }

  apply();
  system.addEventListener("change", apply);
  window.addEventListener("storage", event => {
    if (event.key === key || event.key === null) {
      preference = normalize(event.newValue);
      apply();
    }
  });
  document.addEventListener("DOMContentLoaded", () => {
    const picker = document.querySelector("[data-theme-picker]");
    if (!picker) return;
    const summary = picker.querySelector("summary");
    picker.hidden = false;
    picker.querySelectorAll("[data-theme-option]").forEach(button => {
      button.addEventListener("click", () => {
        preference = normalize(button.dataset.themeOption);
        try { localStorage.setItem(key, preference); } catch (_) { /* Keep working for this page. */ }
        apply();
        picker.open = false;
        summary.focus({ preventScroll: true });
      });
    });
    document.addEventListener("pointerdown", event => {
      if (!picker.contains(event.target)) picker.open = false;
    });
    picker.addEventListener("keydown", event => {
      if (event.key === "Escape" && picker.open) {
        event.preventDefault();
        picker.open = false;
        summary.focus({ preventScroll: true });
      }
    });
    apply();
  });
})();
