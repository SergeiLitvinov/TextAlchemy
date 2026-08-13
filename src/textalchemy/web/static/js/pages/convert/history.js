"use strict";

import {conversionApi, downloadResult} from './api.js';

const labels = {queued: 'В очереди…', running: 'Конвертация…', done: 'Готово', error: 'Ошибка', interrupted: 'Прервана', expired: 'Истёк срок'};
const modeLabels = {balanced: 'Разумный баланс', faithful: 'Максимальное сходство', editable: 'Удобное редактирование'};

export function createHistoryController($, {openPreview, pollJob}) {
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
        const rows = job.tasks.map((task) => {
            const download = task.status === 'done' && task.result_url
                ? `<button type="button" class="btn-link" data-download-url="${window.esc(task.result_url)}" data-filename="${window.esc(task.filename || task.name)}">Скачать</button>` : '';
            const preview = task.status === 'done' ? `<button type="button" class="btn-link" data-preview-task="${window.esc(task.task_id)}">Просмотр</button>` : '';
            const error = ['error', 'interrupted'].includes(task.status) && task.error ? `<small>${window.esc(task.error)}</small>` : '';
            return `<li class="batch-progress-item ${window.esc(task.status)}"><span class="file-name">${window.esc(task.name)}</span>` +
                `<span class="job-state ${window.esc(task.status)}">${window.esc(labels[task.status] || task.status)}</span>${download}${preview}${error}</li>`;
        }).join('');
        return `<ul class="batch-progress-list">${rows || '<li class="field-help">Задач нет</li>'}</ul><div class="row-actions">` +
            `<button type="button" data-rerun-job="${window.esc(job.job_id)}">Перезапустить</button>` +
            `<button type="button" data-delete-job="${window.esc(job.job_id)}">Удалить</button></div>`;
    }

    async function loadDetail(jobId, container) {
        try { container.innerHTML = detailMarkup(await conversionApi.job(jobId)); }
        catch (_) { container.innerHTML = '<p class="field-help">Не удалось загрузить задачу.</p>'; }
    }

    async function rerun(jobId) {
        try {
            const data = await conversionApi.rerunJob(jobId);
            window.toast(data.launched.length ? 'Задача перезапущена' : 'Нечего перезапускать', 'success');
            load();
            if (data.launched?.length) {
                $('batchProgressCard').hidden = false;
                $('batchProgressState').textContent = 'Перезапуск…';
                pollJob(jobId);
            }
        } catch (_) { window.toast('Не удалось перезапустить задачу', 'error'); }
    }

    async function remove(jobId) {
        try { await conversionApi.deleteJob(jobId); window.toast('Задача удалена', 'success'); load(); }
        catch (_) { window.toast('Не удалось удалить задачу', 'error'); }
    }

    $('historyRefresh').addEventListener('click', load);
    for (const container of [$('historyList'), $('batchProgressList')]) container.addEventListener('click', (event) => {
        const download = event.target.closest('[data-download-url]');
        if (download) return void downloadResult(download.dataset.downloadUrl, download.dataset.filename);
        const preview = event.target.closest('[data-preview-task]');
        if (preview) return void openPreview(preview.dataset.previewTask);
        const rerunButton = event.target.closest('[data-rerun-job]');
        if (rerunButton) return void rerun(rerunButton.dataset.rerunJob);
        const deleteButton = event.target.closest('[data-delete-job]');
        if (deleteButton) remove(deleteButton.dataset.deleteJob);
    });

    return {load};
}
