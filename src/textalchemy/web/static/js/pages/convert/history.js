"use strict";

import {conversionApi, downloadResult} from './api.js';

const labels = {queued: 'В очереди…', running: 'Конвертация…', done: 'Готово', error: 'Ошибка', interrupted: 'Прервана', expired: 'Истёк срок'};
labels.cancelled = 'Отменена';
labels.cancelling = 'Отмена…';
const modeLabels = {balanced: 'Разумный баланс', faithful: 'Максимальное сходство', editable: 'Удобное редактирование'};

export function createHistoryController($, {openPreview, pollJob}) {
    async function cancel(jobId, button, taskIds = null) {
        button.disabled = true;
        try {
            const data = await conversionApi.cancelJob(jobId, taskIds);
            window.toast(data.requested.length
                ? `Запрошена отмена файлов: ${data.requested.length}. Готовые результаты доступны для скачивания.`
                : 'Ожидающих или выполняющихся файлов уже нет.', 'info');
            $('batchProgressCard').hidden = false;
            pollJob(jobId);
            load();
        } catch (_) { window.toast('Не удалось отменить пакет. Обновите статусы и повторите попытку.', 'error'); }
        finally { button.disabled = false; }
    }
    async function load() {
        try {
            const data = await conversionApi.jobs();
            render(data.jobs || []);
        } catch (_) { /* history must not block conversion */ }
    }

    function render(jobs) {
        const container = $('historyList');
        container.innerHTML = '';
        if (!jobs.length) {
            container.innerHTML = '<p class="field-help">Пакетные конвертации из этой сессии появятся здесь.</p>';
            return;
        }
        for (const job of jobs) {
            const details = document.createElement('details');
            details.className = 'job-entry';
            details.dataset.job = job.job_id;
            if (job.counts.queued || job.counts.running) details.open = true;
            const total = Object.values(job.counts).reduce((a, b) => a + b, 0);
            const state = job.counts.queued || job.counts.running ? ['running', 'Конвертация…']
                : job.counts.error ? ['error', `${job.counts.error} ошибок`]
                    : job.counts.interrupted ? ['error', `${job.counts.interrupted} прервано`] : ['done', `${job.counts.done}/${total} готово`];
            details.innerHTML = `<summary><span class="job-title">${window.esc(job.files.join(', '))}</span>` +
                `<span class="job-state ${state[0]}">${state[1]}</span><small class="job-mode">${window.esc(modeLabels[job.mode] || 'Разумный баланс')}</small></summary>` +
                '<div class="job-detail">Загружается…</div>';
            details.addEventListener('toggle', () => { if (details.open) loadDetail(job.job_id, details.querySelector('.job-detail')); });
            container.appendChild(details);
        }
    }

    function detailMarkup(job) {
        const cancelButton = job.tasks.some((task) => ['queued', 'running'].includes(task.status))
            ? `<button type="button" data-cancel-job="${window.esc(job.job_id)}">Отменить оставшиеся файлы</button>` : '';
        const retryFailed = job.tasks.some((task) => ['error', 'interrupted', 'cancelled'].includes(task.status))
            ? `<button type="button" data-retry-failed="${window.esc(job.job_id)}">Повторить неудачные</button>` : '';
        const retrySelected = retryFailed
            ? `<button type="button" data-retry-selected="${window.esc(job.job_id)}" disabled>Повторить выбранные (0)</button>` : '';
        const ready = job.tasks.some((task) => task.status === 'done') &&
            !job.tasks.some((task) => ['queued', 'running', 'cancelling'].includes(task.status));
        const archive = ready ? `<button type="button" data-download-url="/api/convert/jobs/${encodeURIComponent(job.job_id)}/archive" data-filename="converted-batch.zip">Скачать готовые результаты ZIP</button>` : '';
        const rows = job.tasks.map((task) => {
            const action = ['error', 'interrupted', 'cancelled'].includes(task.status) ? 'retry'
                : ['queued', 'running'].includes(task.status) ? 'cancel' : task.status === 'done' ? 'archive' : null;
            const purpose = {retry: 'повтора', cancel: 'отмены', archive: 'скачивания'};
            const select = action ? `<label class="retry-choice"><input type="checkbox" data-${action}-task="${window.esc(task.task_id)}" aria-label="Выбрать для ${purpose[action]}: ${window.esc(task.name)}"> Выбрать</label>` : '';
            const download = task.status === 'done' && task.result_url
                ? `<button type="button" class="btn-link" data-download-url="${window.esc(task.result_url)}" data-filename="${window.esc(task.filename || task.name)}">Скачать</button>` : '';
            const preview = task.status === 'done' ? `<button type="button" class="btn-link" data-preview-task="${window.esc(task.task_id)}">Просмотр</button>` : '';
            const error = ['error', 'interrupted'].includes(task.status) && task.error ? `<small>${window.esc(task.error)}</small>` : '';
            const settings = task.target_format ? `<small>${window.esc(task.target_format.toUpperCase())} · ${window.esc(modeLabels[task.mode] || task.mode || '')}</small>` : '';
            return `<li class="batch-progress-item ${window.esc(task.status)}">${select}<span class="file-name">${window.esc(task.name)}</span>` +
                `<span class="job-state ${window.esc(task.status)}">${window.esc(labels[task.status] || task.status)}</span>${settings}${download}${preview}${error}</li>`;
        }).join('');
        const chosen = (action, label, available) => available ? `<button type="button" data-${action}-selected="${window.esc(job.job_id)}" disabled>${label} (0)</button>` : '';
        return `<ul class="batch-progress-list">${rows || '<li class="field-help">Задач нет</li>'}</ul><div class="row-actions">` +
            chosen('archive', 'Скачать выбранные ZIP', job.tasks.some(task => task.status === 'done')) +
            chosen('cancel', 'Отменить выбранные', Boolean(cancelButton)) + archive + retrySelected + retryFailed + cancelButton +
            `<button type="button" data-open-job="${window.esc(job.job_id)}">Открыть пакет</button>` +
            `<button type="button" data-rerun-job="${window.esc(job.job_id)}">Перезапустить</button>` +
            `<button type="button" data-delete-job="${window.esc(job.job_id)}">Удалить</button></div>`;
    }

    async function loadDetail(jobId, container) {
        try { container.innerHTML = detailMarkup(await conversionApi.job(jobId)); }
        catch (_) { container.innerHTML = '<p class="field-help">Не удалось загрузить задачу.</p>'; }
    }

    async function rerun(jobId, failedOnly = false, taskIds = null, button = null) {
        if (button) button.disabled = true;
        try {
            const data = await conversionApi.rerunJob(jobId, failedOnly, taskIds);
            const accepted = data.queued || data.launched;
            const message = taskIds !== null
                ? `Выбранных файлов поставлено в очередь: ${accepted.length}.` : data.launched.length
                ? (failedOnly ? `Повторно запущено файлов: ${data.launched.length}. Готовые результаты сохранены.` : 'Задача перезапущена')
                : 'Нет файлов для повторного запуска: исходники могли истечь или маршрут недоступен.';
            window.toast(message, data.launched.length ? 'success' : 'info');
            if (taskIds !== null && data.skipped?.length) {
                window.toast('Пропущены: ' + data.skipped.map((item) => `${item.name}: ${item.reason}`).join('; '), 'info');
            }
            if (accepted.length > data.launched.length) window.toast('Очередь временно недоступна. Файлы ожидают её перезапуска.', 'info');
            load();
            if (accepted.length) {
                $('batchProgressCard').hidden = false;
                $('batchProgressState').textContent = 'Перезапуск…';
                pollJob(jobId);
            }
        } catch (_) { window.toast('Не удалось перезапустить задачу', 'error'); }
        finally { if (button) button.disabled = false; }
    }

    async function remove(jobId) {
        try { await conversionApi.deleteJob(jobId); window.toast('Задача удалена', 'success'); load(); }
        catch (_) { window.toast('Не удалось удалить задачу', 'error'); }
    }

    $('historyRefresh').addEventListener('click', load);
    $('historyList').addEventListener('change', (event) => {
        if (!event.target.matches('[data-retry-task], [data-cancel-task], [data-archive-task]')) return;
        const detail = event.target.closest('.job-detail');
        for (const [action, label] of [['retry', 'Повторить выбранные'], ['cancel', 'Отменить выбранные'], ['archive', 'Скачать выбранные ZIP']]) {
            const count = detail.querySelectorAll(`[data-${action}-task]:checked`).length;
            const button = detail.querySelector(`[data-${action}-selected]`);
            if (button) { button.disabled = count === 0; button.textContent = `${label} (${count})`; }
        }
    });
    for (const container of [$('historyList'), $('batchProgressList')]) container.addEventListener('click', (event) => {
        for (const action of ['cancel', 'archive']) {
            const button = event.target.closest(`[data-${action}-selected]`);
            if (!button) continue;
            const selected = Array.from(button.closest('.job-detail').querySelectorAll(`[data-${action}-task]:checked`))
                .map(input => input.dataset[`${action}Task`]);
            const jobId = button.dataset[`${action}Selected`];
            if (!selected.length) return;
            if (action === 'cancel') void cancel(jobId, button, selected);
            else void downloadResult(`/api/convert/jobs/${encodeURIComponent(jobId)}/archive?task_ids=${encodeURIComponent(JSON.stringify(selected))}`, 'selected-results.zip');
            return;
        }
        const download = event.target.closest('[data-download-url]');
        if (download) return void downloadResult(download.dataset.downloadUrl, download.dataset.filename);
        const preview = event.target.closest('[data-preview-task]');
        if (preview) return void openPreview(preview.dataset.previewTask);
        const openJob = event.target.closest('[data-open-job]');
        if (openJob) {
            $('batchProgressCard').hidden = false;
            pollJob(openJob.dataset.openJob);
            $('batchProgressCard').scrollIntoView({behavior: 'smooth', block: 'start'});
            return;
        }
        const rerunButton = event.target.closest('[data-rerun-job]');
        const retryFailed = event.target.closest('[data-retry-failed]');
        const retrySelected = event.target.closest('[data-retry-selected]');
        if (retrySelected) {
            const taskIds = Array.from(retrySelected.closest('.job-detail').querySelectorAll('[data-retry-task]:checked'))
                .map((input) => input.dataset.retryTask);
            if (taskIds.length) void rerun(retrySelected.dataset.retrySelected, true, taskIds, retrySelected);
            return;
        }
        if (retryFailed) return void rerun(retryFailed.dataset.retryFailed, true);
        if (rerunButton) return void rerun(rerunButton.dataset.rerunJob);
        const deleteButton = event.target.closest('[data-delete-job]');
        const cancelButton = event.target.closest('[data-cancel-job]');
        if (cancelButton) return void cancel(cancelButton.dataset.cancelJob, cancelButton);
        if (deleteButton) remove(deleteButton.dataset.deleteJob);
    });

    return {load, cancel};
}
