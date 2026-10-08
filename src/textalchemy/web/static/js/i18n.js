"use strict";

const LANGUAGE_KEY = "textalchemy-language";
let messages = {};
window.translate = (key, fallback, values = {}) =>
  (messages[key] || fallback).replace(/\{(\w+)\}/g, (match, name) => values[name] ?? match);

async function loadLocale(code) {
  const response = await fetch(`/api/locales/${encodeURIComponent(code)}`);
  if (!response.ok) throw new Error("Не удалось загрузить язык интерфейса");
  const catalog = await response.json();
  messages = catalog.messages;
  document.documentElement.lang = catalog.code;
  document.documentElement.dataset.locale = catalog.code;
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const value = catalog.messages[element.dataset.i18n];
    if (value) element.textContent = window.translate(element.dataset.i18n, value, JSON.parse(element.dataset.i18nParams || '{}'));
  });
  localStorage.setItem(LANGUAGE_KEY, catalog.code);
}

loadLocale(localStorage.getItem(LANGUAGE_KEY) || "ru").catch(() => {});
