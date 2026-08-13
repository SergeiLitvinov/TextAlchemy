/* TextAlchemy — общий клиентский хелпер.
 *
 * Предоставляет:
 *  - api(path, opts)        — fetch с JSON-телом и нормальной обработкой ошибок
 *  - toast(msg, type)       — всплывающее уведомление
 *  - setLoading(btn, on)    — спиннер на кнопке
 *  - esc(str)               — экранирование HTML (защита от XSS)
 *  - загрузка/сохранение темы в localStorage
 */
(function () {
  "use strict";

  const THEME_KEY = "textalchemy-theme";

  // ── Тема ───────────────────────────────────────────────
  function applyTheme(theme) {
    const normalized = theme === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = normalized;
    document.documentElement.style.colorScheme = normalized;
    const toggle = document.querySelector(".theme-toggle");
    if (toggle) {
      const nextLabel = normalized === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
      toggle.setAttribute("aria-label", nextLabel);
      toggle.setAttribute("title", nextLabel);
      const icon = toggle.querySelector("use");
      if (icon) icon.setAttribute("href", normalized === "dark" ? "#icon-sun" : "#icon-moon");
    }
  }

  function toggleTheme() {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    const preferred = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    applyTheme(saved || preferred);
  }

  window.toggleTheme = toggleTheme;

  function initNavigation() {
    const openButton = document.querySelector("[data-nav-open]");
    const closeTarget = document.querySelector("[data-nav-close]");
    if (!openButton) return;

    function setOpen(open) {
      document.body.classList.toggle("nav-open", open);
      openButton.setAttribute("aria-expanded", String(open));
      if (closeTarget) closeTarget.hidden = !open;
    }

    openButton.addEventListener("click", () => setOpen(!document.body.classList.contains("nav-open")));
    if (closeTarget) closeTarget.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setOpen(false);
    });
    const desktopMedia = window.matchMedia("(min-width: 1051px)");
    if (desktopMedia.addEventListener) {
      desktopMedia.addEventListener("change", (event) => {
        if (event.matches) setOpen(false);
      });
    }
  }

  // ── Тосты ──────────────────────────────────────────────
  function ensureToastContainer() {
    let c = document.getElementById("toast-container");
    if (!c) {
      c = document.createElement("div");
      c.id = "toast-container";
      c.className = "toast-container";
      document.body.appendChild(c);
    }
    return c;
  }

  function toast(message, type) {
    type = type || "info";
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = message;
    ensureToastContainer().appendChild(el);
    requestAnimationFrame(() => {
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    });
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transform = "translateY(8px)";
      setTimeout(() => el.remove(), 250);
    }, 3500);
  }

  window.toast = toast;

  // ── Спиннер на кнопке ──────────────────────────────────
  function setLoading(btn, on) {
    if (!btn) return;
    if (on) {
      if (btn.dataset.busy === "1") return;
      btn.dataset.busy = "1";
      btn.dataset.label = btn.textContent;
      btn.disabled = true;
      btn.textContent = "⏳ …";
    } else {
      btn.dataset.busy = "0";
      btn.disabled = false;
      btn.textContent = btn.dataset.label || btn.textContent;
    }
  }

  window.setLoading = setLoading;

  // ── Экранирование HTML ─────────────────────────────────
  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  window.esc = esc;

  // ── API-клиент ─────────────────────────────────────────
  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    } else if (opts.formData) {
      init.body = opts.formData;
    } else if (opts.body) {
      init.body = opts.body;
    }
    let res;
    try {
      res = await fetch(path, init);
    } catch (networkErr) {
      toast("Сетевая ошибка: " + networkErr.message, "error");
      throw networkErr;
    }
    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      try {
        data = await res.json();
      } catch (_) {
        data = null;
      }
    }
    if (!res.ok) {
      const msg =
        (data && (data.error || data.detail)) ||
        `Ошибка ${res.status} (${res.statusText})`;
      toast(msg, "error");
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  window.api = api;

  // ── Инициализация при загрузке ─────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initNavigation();
  });
})();
