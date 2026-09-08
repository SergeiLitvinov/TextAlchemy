"use strict";

import {conversionApi, downloadResult} from './convert/api.js';
import {createHistoryController} from './convert/history.js';
import {createPreviewController} from './convert/preview.js';
import {createConversionView} from './convert/view.js';
import {renderObjectGate, renderQualityGate, renderTextGate} from './convert/quality.js';

const $ = (id) => document.getElementById(id);
const modeDescriptions = {
    balanced: 'Оптимальный баланс оформления и редактируемости.',
    faithful: 'Приоритет визуального сходства с оригиналом.',
    editable: 'Приоритет структуры и удобства дальнейшего редактирования.',
};
const state = {
    capabilities: {sources: []}, pendingFile: null, selectedSource: null,
    batchFiles: null, batchTargets: null, activeTask: null, activeTaskId: null, inspectionRequest: 0,
};
const view = createConversionView($);
let history;

function sourceFor(file) {
    const name = file.name.toLowerCase();
    return state.capabilities.sources.find((source) => source.extensions.some((extension) => name.endsWith(extension)));
}

function batchTargets(sources) {
    const common = new Set(sources[0].targets.map((item) => item.format));
    for (const source of sources.slice(1)) {
        const formats = new Set(source.targets.map((item) => item.format));
        for (const format of Array.from(common)) if (!formats.has(format)) common.delete(format);
    }
    return sources[0].targets.filter((item) => common.has(item.format)).map((item) => {
        const modeSets = sources.map((source) => new Set(source.targets.find((target) => target.format === item.format)?.modes || []));
        let modes = Array.from(modeSets[0]);
        for (const set of modeSets.slice(1)) modes = modes.filter((mode) => set.has(mode));
        return {...item, modes};
    }).filter((item) => item.modes.length);
}

function targets() {
    return state.batchFiles ? state.batchTargets : (state.selectedSource?.targets || []);
}

function selectedTarget() {
    return targets().find((target) => target.format === $('target').value);
}

function updateModeHelp() {
    const plan = selectedTarget()?.plans[$('mode').value];
    $('mode-help').textContent = modeDescriptions[$('mode').value];
    const route = plan?.descriptions.length
        ? `Маршрут: ${plan.descriptions.join(' → ')}` : 'Прямое преобразование без промежуточных этапов';
    if (!plan) {
        $('route-help').textContent = route;
        return;
    }
    const visual = Math.round((plan.visual_score || 0) * 100);
    const editable = Math.round((plan.editability_score || 0) * 100);
    $('route-help').textContent = `${route}. Прогноз: сходство ${visual}%, редактируемость ${editable}%.`;
}

function updateTarget() {
    const target = selectedTarget();
    if (!target) return;
    const modes = new Set(target.modes);
    for (const option of $('mode').options) option.disabled = !modes.has(option.value);
    if (!modes.has($('mode').value)) $('mode').value = target.modes[0];
    updateModeHelp();
}

async function inspect(file) {
    const request = ++state.inspectionRequest;
    $('inspectionState').textContent = 'Проверяем…';
    $('inspectionMetrics').innerHTML = '';
    $('inspectionMessage').textContent = 'Анализируем страницы, текст, таблицы, изображения и формулы.';
    try {
        const data = await conversionApi.inspect(file);
        if (request === state.inspectionRequest) view.inspection(data.inspection);
    } catch (_) {
        if (request !== state.inspectionRequest) return;
        $('inspectionState').textContent = 'Проверка недоступна';
        $('inspectionMessage').textContent = 'Конвертацию всё равно можно запустить.';
    }
}

function selectFile(file) {
    const source = sourceFor(file);
    if (!source) return view.status('Для этого формата нет доступных маршрутов конвертации.', 'error');
    Object.assign(state, {batchFiles: null, batchTargets: null, pendingFile: file, selectedSource: source});
    $('batchFileBlock').hidden = true;
    $('batchConvertBtn').hidden = true;
    $('convertBtn').hidden = false;
    $('singleFileBlock').hidden = false;
    $('sourceInspection').hidden = false;
    $('sourceBadge').textContent = source.label;
    $('sourceFilename').textContent = file.name;
    $('conversionSetup').hidden = false;
    $('resultCard').hidden = true;
    view.status('');
    $('target').innerHTML = source.targets.map((item) =>
        `<option value="${window.esc(item.format)}">${window.esc(item.label)} (${window.esc(item.extension)})</option>`).join('');
    updateTarget();
    inspect(file);
}

function selectBatch(files) {
    const sources = files.map(sourceFor);
    if (sources.some((source) => !source)) return view.status('Один из файлов имеет формат без доступных маршрутов конвертации.', 'error');
    const commonTargets = batchTargets(sources);
    if (!commonTargets.length) return view.status('Для выбранных файлов нет общего формата результата. Конвертируйте их по отдельности.', 'error');
    Object.assign(state, {batchFiles: files, batchTargets: commonTargets, pendingFile: null, selectedSource: null});
    $('conversionSetup').hidden = false;
    $('resultCard').hidden = true;
    $('singleFileBlock').hidden = true;
    $('sourceInspection').hidden = true;
    $('convertBtn').hidden = true;
    $('batchFileBlock').hidden = false;
    $('batchConvertBtn').hidden = false;
    $('batchFileSummary').textContent = `${files.length} файлов — общий формат результата`;
    $('batchFileList').innerHTML = files.map((file) =>
        `<li><span class="file-name">${window.esc(file.name)}</span><small>${window.esc(sourceFor(file).label)}</small></li>`).join('');
    $('target').innerHTML = commonTargets.map((item) =>
        `<option value="${window.esc(item.format)}">${window.esc(item.label)} (${window.esc(item.extension)})</option>`).join('');
    updateTarget();
    view.status('');
}

function handleFiles(files) {
    if (files.length === 1) selectFile(files[0]);
    else if (files.length > 1) selectBatch(files);
}

function renderReport(data, failed = false, taskId = state.activeTaskId) {
    const report = data.report || {issues: [], metrics: {}};
    const issues = report.issues || [];
    const losses = issues.filter((item) => item.severity === 'loss');
    const warnings = issues.filter((item) => item.severity === 'warning');
    const planned = report.metrics?.plan?.steps || [];
    const steps = planned.length ? planned.map((step) => step.description || step.id) : (report.metrics?.executed_steps || []);
    $('resultCard').hidden = false;
    $('resultTitle').textContent = failed ? 'Конвертация требует внимания' : 'Документ готов';
    $('resultFilename').textContent = data.filename || 'Результат не создан';
    $('resultMode').textContent = $('mode').selectedOptions[0]?.textContent || '—';
    $('resultRoute').textContent = steps.length ? steps.join(' → ') : 'Прямое преобразование';
    $('qualityBadge').className = `quality-badge ${failed ? 'bad' : losses.length ? 'warn' : 'good'}`;
    $('qualityBadge').textContent = failed ? 'Ошибка' : losses.length ? `Сообщений о потерях: ${losses.length}` : warnings.length ? `Замечания: ${warnings.length}` : 'Потерь не зарегистрировано';
    renderQualityGate($, report);
    renderObjectGate($, report);
    renderTextGate($, report);
    $('issuesSection').hidden = !issues.length;
    $('issueList').innerHTML = issues.map((issue) =>
        `<li class="issue-${window.esc(issue.severity)}"><strong>${window.esc(issue.feature)}</strong><span>${window.esc(issue.message)}</span></li>`).join('');
    view.comparison(data.comparison, data.inspection_error);
    preview.init(failed ? null : taskId);
    $('downloadBtn').hidden = failed;
    $('resultCard').scrollIntoView({behavior: 'smooth', block: 'start'});
}

const preview = createPreviewController($, (data, taskId) => {
    state.activeTaskId = taskId;
    renderReport(data, false, taskId);
});

async function pollTask(url) {
    try {
        const data = await conversionApi.taskStatus(url);
        if (data.status === 'done') {
            view.progress(true, 100, 'Готово');
            renderReport(data);
            window.setLoading($('convertBtn'), false);
            setTimeout(() => view.progress(false, 0, ''), 500);
        } else if (['error', 'interrupted'].includes(data.status)) {
            view.progress(false, 0, '');
            window.setLoading($('convertBtn'), false);
            view.status(data.error ? `Не удалось конвертировать: ${data.error}` : 'Задача прервана перезапуском сервера', 'error');
            if (data.report) renderReport(data, true);
        } else {
            view.progress(true, 70, 'Конвертация и проверка результата…');
            setTimeout(() => pollTask(url), 900);
        }
    } catch (_) { view.progress(false, 0, ''); window.setLoading($('convertBtn'), false); }
}

async function pollJob(jobId) {
    try {
        const data = await conversionApi.job(jobId);
        view.batchProgress(data.tasks);
        if (data.tasks.some((task) => ['queued', 'running'].includes(task.status))) {
            $('batchProgressState').textContent = 'Конвертируем…';
            setTimeout(() => pollJob(jobId), 900);
        } else { $('batchProgressState').textContent = 'Готово'; history.load(); }
    } catch (_) { $('batchProgressState').textContent = 'Не удалось получить статус'; }
}

history = createHistoryController($, {openPreview: preview.open, pollJob});

async function startSingle() {
    const target = selectedTarget();
    if (!state.pendingFile || !state.selectedSource || !target) return;
    if ($('textPreservation').value === 'flow' && !$('maxTextEdits').reportValidity()) return;
    $('resultCard').hidden = true;
    view.status('');
    view.progress(true, 20, 'Загрузка документа…');
    window.setLoading($('convertBtn'), true);
    try {
        state.activeTask = await conversionApi.start(
            state.pendingFile, target.format, $('mode').value, $('minRetention').value,
            $('maxLossIssues').value, $('maxLostObjects').value, false, $('textPreservation').value,
            $('textPreservation').value === 'flow' ? $('maxTextEdits').value : '');
        state.activeTaskId = state.activeTask.task_id;
        view.progress(true, 45, 'Анализ структуры и выбор маршрута…');
        pollTask(state.activeTask.status);
    } catch (_) { view.progress(false, 0, ''); window.setLoading($('convertBtn'), false); }
}

async function startBatch() {
    const target = selectedTarget();
    if (!state.batchFiles || !target) return;
    if ($('textPreservation').value === 'flow' && !$('maxTextEdits').reportValidity()) return;
    view.status('');
    $('batchConvertBtn').hidden = true;
    try {
        const job = await conversionApi.startBatch(
            state.batchFiles, target.format, $('mode').value, $('minRetention').value,
            $('maxLossIssues').value, $('maxLostObjects').value, false, $('textPreservation').value,
            $('textPreservation').value === 'flow' ? $('maxTextEdits').value : '');
        $('batchProgressCard').hidden = false;
        $('batchProgressState').textContent = 'Конвертируем…';
        $('batchProgressCard').scrollIntoView({behavior: 'smooth', block: 'start'});
        pollJob(job.job_id);
    } catch (_) { $('batchConvertBtn').hidden = false; }
}

function bindUpload() {
    const drop = $('dropZone');
    drop.addEventListener('click', () => $('fileInput').click());
    drop.addEventListener('keydown', (event) => {
        if (['Enter', ' '].includes(event.key)) { event.preventDefault(); $('fileInput').click(); }
    });
    drop.addEventListener('dragover', (event) => { event.preventDefault(); drop.classList.add('dragover'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
    drop.addEventListener('drop', (event) => { event.preventDefault(); drop.classList.remove('dragover'); handleFiles(Array.from(event.dataTransfer.files)); });
    $('fileInput').addEventListener('change', () => handleFiles(Array.from($('fileInput').files)));
    for (const id of ['replaceBtn', 'batchReplaceBtn']) $(id).addEventListener('click', () => $('fileInput').click());
}

async function init() {
    bindUpload();
    $('target').addEventListener('change', updateTarget);
    $('mode').addEventListener('change', updateModeHelp);
    $('textPreservation').addEventListener('change', () => {
        const enabled = $('textPreservation').value === 'flow';
        $('textEditBudget').hidden = !enabled;
        $('maxTextEdits').disabled = !enabled;
    });
    $('convertBtn').addEventListener('click', startSingle);
    $('batchConvertBtn').addEventListener('click', startBatch);
    $('downloadBtn').addEventListener('click', () => state.activeTask && downloadResult(state.activeTask.result, $('resultFilename').textContent));
    $('anotherBtn').addEventListener('click', () => {
        $('resultCard').hidden = true;
        $('conversionSetup').hidden = true;
        $('fileInput').value = '';
        Object.assign(state, {pendingFile: null, selectedSource: null, batchFiles: null, batchTargets: null, activeTaskId: null});
        state.inspectionRequest += 1;
        preview.reset();
        $('dropZone').scrollIntoView({behavior: 'smooth', block: 'center'});
    });
    history.load();
    try {
        state.capabilities = await conversionApi.capabilities();
        const extensions = state.capabilities.sources.flatMap((source) => source.extensions);
        $('fileInput').accept = extensions.join(',');
        $('drop-hint').textContent = extensions.map((item) => item.slice(1).toUpperCase()).join(', ') +
            ' · формат определится автоматически · можно выбрать несколько файлов';
    } catch (_) { $('drop-hint').textContent = 'Не удалось получить список доступных форматов'; }
}

init();
