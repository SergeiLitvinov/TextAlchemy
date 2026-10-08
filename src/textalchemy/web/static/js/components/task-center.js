"use strict";
import {createDrawer} from './drawer.js';

const drawer = document.getElementById("taskCenter");
const list = document.getElementById("globalTaskList");
const status = document.getElementById("taskCenterStatus");
const badge = document.getElementById("activeTaskCount");
const clearButton = document.getElementById("clearFinishedTasks");
const storageSize = document.getElementById("taskStorageSize");
const backdrop = document.querySelector(".task-center-backdrop");
const triggers = [...document.querySelectorAll("[data-task-center-open]")];
const closeButtons = [...document.querySelectorAll("[data-task-center-close]")];
const labels = {
  queued: "В очереди",
  running: "Выполняется",
  done: "Готово",
  error: "Ошибка",
  interrupted: "Прервано",
  cancelling: "Отменяем…",
  cancelled: "Отменено",
};
const modes = {balanced: "Разумный баланс", faithful: "Максимальное сходство", editable: "Удобное редактирование"};
let refreshTimer = null;

createDrawer({
  panel: drawer, triggers, closeTargets: closeButtons,
  background: [document.querySelector('.header'), document.querySelector('.app-layout')],
  fallbackFocus: () => document.querySelector('.header [data-task-center-open]'),
  onChange(open) {
    drawer.classList.toggle('open', open);
    drawer.inert = !open;
    document.body.classList.toggle('task-center-open', open);
    if (backdrop) backdrop.hidden = !open;
    if (open) loadTasks();
  },
});

function ageLabel(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 60) return "только что";
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes} мин назад` : `${Math.floor(minutes / 60)} ч назад`;
}

function sizeLabel(bytes) {
  if (!bytes) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / (1024 ** index);
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

function taskMarkup(task) {
  const route = [task.source_format, task.target_format].filter(Boolean).join(" → ");
  const actions = [];
  if (task.result_url) actions.push(`<a class="btn-link" data-task-focus="download" href="${window.esc(task.result_url)}">Скачать</a>`);
  if (task.can_cancel) actions.push(`<button class="btn-link" type="button" data-task-focus="cancel" data-task-action="cancel" data-task-id="${window.esc(task.task_id)}">Отменить</button>`);
  if (task.can_rerun) actions.push(`<button class="btn-link" type="button" data-task-focus="rerun" data-task-action="rerun" data-task-id="${window.esc(task.task_id)}">Повторить</button>`);
  const error = task.error ? `<small class="task-error">${window.esc(task.error)}</small>` : "";
  return `<article class="global-task ${window.esc(task.status)}" data-task-id="${window.esc(task.task_id)}">
    <span class="task-state-dot" aria-hidden="true"></span>
    <div><strong>${window.esc(task.filename)}</strong><small>${window.esc(route || modes[task.mode] || "Обработка документа")} · ${window.esc(ageLabel(task.age_seconds))}</small>${error}</div>
    <span class="task-status">${window.esc(labels[task.status] || task.status)}</span><span class="task-actions">${actions.join("")}</span>
  </article>`;
}

async function loadTasks() {
  if (!drawer) return;
  try {
    const data = await window.api("/api/tasks");
    badge.textContent = String(data.active || 0);
    badge.hidden = !data.active;
    status.textContent = data.active ? `${data.active} выполняется` : "Нет активных задач";
    storageSize.textContent = sizeLabel(data.storage?.bytes || 0);
    clearButton.hidden = !data.tasks.some((task) => !["queued", "running", "cancelling"].includes(task.status));
    const focused = list.contains(document.activeElement) ? document.activeElement : null;
    const taskId = focused?.closest('article')?.dataset.taskId;
    const action = focused?.dataset.taskFocus;
    list.innerHTML = data.tasks.length
      ? data.tasks.map(taskMarkup).join("")
      : '<div class="task-center-empty"><span aria-hidden="true">✓</span><strong>Задач пока нет</strong><small>Новые конвертации появятся здесь и останутся доступны на всех страницах.</small></div>';
    if (focused && action && taskId) {
      const replacement = list.querySelector(`article[data-task-id="${CSS.escape(taskId)}"] [data-task-focus="${CSS.escape(action)}"]`);
      (replacement || drawer.querySelector('[data-task-center-close]')).focus();
    }
    const hasActive = Boolean(data.active);
    clearTimeout(refreshTimer);
    if (hasActive) refreshTimer = setTimeout(loadTasks, 1500);
  } catch (_) {
    status.textContent = "Не удалось загрузить задачи";
  }
}

const clearDialog = document.getElementById('clearTasksDialog');
clearButton?.addEventListener('click', () => { clearDialog.returnValue = ''; clearDialog.showModal(); });
clearDialog?.addEventListener('close', async () => {
  if (clearDialog.returnValue !== 'clear') return;
  try {
    await window.api("/api/tasks/finished", {method: "DELETE"});
    window.toast("Завершённые задачи удалены", "success");
    loadTasks();
  } catch (_) { status.textContent = 'Не удалось очистить задачи. Попробуйте ещё раз.'; }
});
list?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-task-action]");
  if (!button) return;
  button.disabled = true;
  const action = button.dataset.taskAction;
  try {
    await window.api(`/api/tasks/${encodeURIComponent(button.dataset.taskId)}/${action}`, {method: "POST"});
    window.toast(action === "cancel" ? "Отмена запрошена" : "Задача запущена повторно", "success");
    loadTasks();
  } catch (error) {
    window.toast(error.message || "Не удалось изменить задачу", "error");
    button.disabled = false;
  }
});
loadTasks();
