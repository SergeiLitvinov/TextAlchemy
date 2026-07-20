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
  function applyTheme(dark) {
    const root = document.documentElement;
    const vars = dark
      ? {
          "--bg": "#0f172a",
          "--surface": "#1e293b",
          "--text": "#f1f5f9",
          "--text-muted": "#94a3b8",
          "--border": "#334155",
        }
      : {
          "--bg": "#f5f5f5",
          "--surface": "#ffffff",
          "--text": "#1e293b",
          "--text-muted": "#64748b",
          "--border": "#e2e8f0",
        };
    for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
  }

  function toggleTheme() {
    const isDark =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--bg")
        .trim() === "#0f172a";
    const next = !isDark;
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next ? "dark" : "light");
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    applyTheme(saved === "dark");
  }

  window.toggleTheme = toggleTheme;

  // ── Тосты ──────────────────────────────────────────────
  function ensureToastContainer() {
    let c = document.getElementById("toast-container");
    if (!c) {
      c = document.createElement("div");
      c.id = "toast-container";
      c.style.cssText =
        "position:fixed;top:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:.5rem;max-width:360px";
      document.body.appendChild(c);
    }
    return c;
  }

  function toast(message, type) {
    type = type || "info";
    const colors = {
      success: "#16a34a",
      error: "#dc2626",
      info: "#2563eb",
      warning: "#d97706",
    };
    const el = document.createElement("div");
    el.textContent = message;
    el.style.cssText =
      "padding:.75rem 1rem;border-radius:8px;color:#fff;font-size:.9rem;" +
      "box-shadow:0 4px 12px rgba(0,0,0,.25);opacity:0;transform:translateY(-8px);" +
      "transition:opacity .2s,transform .2s;background:" +
      (colors[type] || colors.info);
    ensureToastContainer().appendChild(el);
    requestAnimationFrame(() => {
      el.style.opacity = "1";
      el.style.transform = "translateY(0)";
    });
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transform = "translateY(-8px)";
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
  document.addEventListener("DOMContentLoaded", initTheme);
})();
