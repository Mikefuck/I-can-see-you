/* Run before the stylesheet so a remembered dark theme never starts with a white page. */
(() => {
  "use strict";
  const key = "focus-ledger.theme";
  const labels = { system: "跟随系统", light: "浅色", dark: "深色" };
  const normalize = value => Object.hasOwn(labels, value) ? value : "system";
  const system = matchMedia("(prefers-color-scheme: dark)");
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  // Run in the head, before a cross-document transition captures the incoming page.
  window.addEventListener("pagereveal", event => {
    if (event.viewTransition) {
      document.documentElement.classList.add("has-page-transition");
      event.viewTransition.ready.catch(() => document.documentElement.classList.remove("has-page-transition"));
      event.viewTransition.finished.catch(() => {}); // Redirects or a newer navigation may skip the native transition.
    }
  });
  let preference = "system";
  try { preference = normalize(localStorage.getItem(key)); } catch (_) { /* Storage can be disabled. */ }

  function apply() {
    const theme = preference === "system" ? (system.matches ? "dark" : "light") : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themePreference = preference;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#282925" : "#f6f1df";
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
  const syncVisibility = () => document.documentElement.classList.toggle("is-page-hidden", document.hidden);
  syncVisibility();
  document.addEventListener("visibilitychange", syncVisibility);
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
    const options = picker.querySelector(".theme-options");
    let closing = null;
    function closePicker() {
      if (!picker.open || closing) return;
      if (calm.matches || !options.animate) { picker.open = false; return; }
      closing = options.animate([
        { opacity: 1, transform: "translateY(0) scale(1)" },
        { opacity: 0, transform: "translateY(-4px) scale(.98)" },
      ], { duration: 140, easing: "ease-out" });
      closing.onfinish = () => { picker.open = false; closing = null; };
    }
    summary.addEventListener("click", event => {
      event.preventDefault();
      if (closing) { closing.cancel(); closing = null; }
      else if (picker.open) closePicker();
      else picker.open = true;
    });
    calm.addEventListener("change", () => {
      if (calm.matches && closing) { closing.cancel(); closing = null; picker.open = false; }
    });
    picker.hidden = false;
    picker.querySelectorAll("[data-theme-option]").forEach(button => {
      button.addEventListener("click", () => {
        preference = normalize(button.dataset.themeOption);
        try { localStorage.setItem(key, preference); } catch (_) { /* Keep working for this page. */ }
        apply();
        closePicker();
        summary.focus({ preventScroll: true });
      });
    });
    document.addEventListener("pointerdown", event => {
      if (!picker.contains(event.target)) closePicker();
    });
    picker.addEventListener("keydown", event => {
      if (event.key === "Escape" && picker.open) {
        event.preventDefault();
        closePicker();
        summary.focus({ preventScroll: true });
      }
    });
    apply();
  });
})();
