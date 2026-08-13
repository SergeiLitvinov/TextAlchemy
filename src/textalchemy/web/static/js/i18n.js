"use strict";

const LANGUAGE_KEY = "textalchemy-language";
const dialog = document.getElementById("languageDialog");
const triggers = [...document.querySelectorAll("[data-language-open]")];

async function loadLocale(code) {
  const response = await fetch(`/api/locales/${encodeURIComponent(code)}`);
  if (!response.ok) throw new Error("Не удалось загрузить язык интерфейса");
  const catalog = await response.json();
  document.documentElement.lang = catalog.code;
  document.documentElement.dataset.locale = catalog.code;
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const value = catalog.messages[element.dataset.i18n];
    if (value) element.textContent = value;
  });
  localStorage.setItem(LANGUAGE_KEY, catalog.code);
}

triggers.forEach((trigger) => trigger.addEventListener("click", () => dialog?.showModal()));
dialog?.addEventListener("change", async (event) => {
  if (event.target.name !== "interface-language") return;
  try {
    await loadLocale(event.target.value);
    dialog.close();
  } catch (error) {
    window.toast(error.message, "error");
  }
});

loadLocale(localStorage.getItem(LANGUAGE_KEY) || "ru").catch(() => {});
