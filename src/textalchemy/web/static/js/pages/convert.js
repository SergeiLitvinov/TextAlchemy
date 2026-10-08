"use strict";

const [{conversionApi, downloadResult}, {createBatchFilter}, {createBatchOptions},
    {renderCatalog, renderGuidance, unavailableModeHelp}, {createHistoryController}, {renderIssues},
    {createPreviewController}, {createConversionView}, {createExperienceController},
    {renderPdfVectors, renderHeadingGate, renderEmphasisGate, renderFormulaGate, renderObjectGate, renderQualityGate, renderTextGate},
    {renderTargetChecks}] = await Promise.all([
    'api', 'batch-filter', 'batch-options', 'catalog', 'history', 'issues', 'preview', 'view', 'experience', 'quality', 'target-checks'
].map(name => import(`./convert/${name}.js` + new URL(import.meta.url).search)));

const $ = (id) => document.getElementById(id);
const modeDescriptions = {
    balanced: 'Оптимальный баланс оформления и редактируемости.',
    faithful: 'Приоритет визуального сходства с оригиналом.',
    editable: 'Приоритет структуры и удобства дальнейшего редактирования.',
};
const state = {
    capabilities: {sources: []}, pendingFile: null, selectedSource: null,
    batchFiles: null, batchTargets: null, activeTask: null, activeTaskId: null, resultTaskId: null, inspectionRequest: 0,
};
const view = createConversionView($);
const batchFilter = createBatchFilter($, view.batchProgress);
const batchOptions = createBatchOptions($);
const experience = createExperienceController($, resetBatch => {
    updateTarget();
    batchOptions.defaults($('target').value, $('mode').value, resetBatch);
});
let history;
let batchPollVersion = 0;

function sourceFor(file) {
    const name = file.name.toLowerCase();
    return state.capabilities.sources.find((source) => source.extensions.some((extension) => name.endsWith(extension)));
}

function unsupportedInput(file) {
    const name = file.name.toLowerCase();
    const matches = item => item.extensions.some(extension => name.endsWith(extension));
    const unsupported = state.capabilities.unsupported_inputs?.find(matches);
    if (unsupported) return unsupported.message;
    const unavailable = state.capabilities.unavailable_sources?.find(matches);
    return unavailable?.unavailable_targets?.flatMap(target => Object.values(target.unavailable_modes || {}))
        .find(reason => reason.code === 'missing_dependencies')?.message;
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
    const sources = state.batchFiles ? state.batchFiles.map(sourceFor) : [state.selectedSource].filter(Boolean);
    const unavailable = Array.from($('mode').options).filter((option) => option.disabled).map((option) => option.value);
    if (unavailable.length) {
        $('mode-help').textContent += ' ' + unavailableModeHelp(sources, $('target').value, unavailable);
    }
    $('routeGuidance').hidden = !renderGuidance($('routeGuidanceList'), sources, $('target').value);
    if (state.batchFiles) {
        batchOptions.defaults($('target').value, $('mode').value);
        $('route-help').textContent = 'Для каждого файла будет выбран свой маршрут. Сохранность зависит от исходного формата; итоговые потери будут показаны в отчёте каждого файла.';
        return;
    }
    const route = plan?.descriptions.length
        ? `Маршрут: ${plan.descriptions.join(' → ')}` : 'Прямое преобразование без промежуточных этапов';
    if (!plan) {
        $('route-help').textContent = route;
        return;
    }
    const visual = Math.round((plan.visual_score || 0) * 100);
    const editable = Math.round((plan.editability_score || 0) * 100);
    $('route-help').textContent = `${route}. Прогноз: сходство ${visual}%, редактируемость ${editable}%. Это оценка маршрута, а не измерение вашего результата.`;
}

function updateTarget() {
    const target = selectedTarget();
    if (!target) return;
    const modes = new Set(target.modes);
    for (const option of $('mode').options) option.disabled = !modes.has(option.value);
    if (!experience.expert()) $('mode').value = modes.has('balanced') ? 'balanced' : target.modes[0];
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
    if (!source) return view.status(unsupportedInput(file) || 'Для этого формата нет доступных маршрутов конвертации.', 'error');
    $('filePickerWrap').hidden = true;
    experience.batchRequired(false);
    experience.stage(1);
    Object.assign(state, {batchFiles: null, batchTargets: null, pendingFile: file, selectedSource: source});
    $('batchFileBlock').hidden = true;
    $('batchIndividualOptions').hidden = true;
    $('batchConvertBtn').hidden = true;
    $('convertBtn').hidden = false;
    $('singleFileBlock').hidden = false;
    $('sourceInspection').hidden = ['djvu', 'txt'].includes(source.format);
    $('txtInputProfile').hidden = source.format !== 'txt';
    $('sourceBadge').textContent = source.label;
    $('sourceFilename').textContent = file.name;
    $('pdfPreparation').hidden = source.format !== 'pdf';
    $('conversionSetup').hidden = false;
    $('resultCard').hidden = true;
    view.status('');
    $('target').innerHTML = source.targets.map((item) =>
        `<option value="${window.esc(item.format)}">${window.esc(item.label)} (${window.esc(item.extension)})</option>`).join('');
    if (source.targets.some((target) => target.format === source.default_target)) $('target').value = source.default_target;
    updateTarget();
    if (!['djvu', 'txt'].includes(source.format)) inspect(file);
}

function selectBatch(files) {
    const sources = files.map(sourceFor);
    if (sources.some((source) => !source)) return view.status(files.map(unsupportedInput).find(Boolean) || 'Один из файлов имеет формат без доступных маршрутов конвертации.', 'error');
    $('filePickerWrap').hidden = true;
    $('txtInputProfile').hidden = !sources.some(source => source.format === 'txt');
    const sharedTargets = batchTargets(sources);
    experience.batchRequired(!sharedTargets.length);
    experience.stage(1);
    const commonTargets = sharedTargets.length ? sharedTargets : sources[0].targets;
    Object.assign(state, {batchFiles: files, batchTargets: commonTargets, pendingFile: null, selectedSource: null});
    $('pdfPreparation').hidden = true;
    $('conversionSetup').hidden = false;
    $('resultCard').hidden = true;
    $('singleFileBlock').hidden = true;
    $('sourceInspection').hidden = true;
    $('convertBtn').hidden = true;
    $('batchFileBlock').hidden = false;
    $('batchIndividualOptions').hidden = false;
    $('batchIndividualOptions').open = !sharedTargets.length;
    $('batchConvertBtn').hidden = false;
    $('batchFileSummary').textContent = `${files.length} файлов — общие или индивидуальные настройки`;
    $('batchFileList').innerHTML = files.map((file) =>
        `<li><span class="file-name">${window.esc(file.name)}</span><small>${window.esc(sourceFor(file).label)}</small></li>`).join('');
    $('target').innerHTML = commonTargets.map((item) =>
        `<option value="${window.esc(item.format)}">${window.esc(item.label)} (${window.esc(item.extension)})</option>`).join('');
    if (commonTargets.some((target) => target.format === sources[0].default_target)) $('target').value = sources[0].default_target;
    updateTarget();
    batchOptions.mount(files, sources);
    if (!sharedTargets.length) experience.enableForBatch();
    view.status('');
}

function handleFiles(files) {
    if ($('conversionWorkspace').dataset.processing === 'true') return;
    if (files.length === 1) selectFile(files[0]);
    else if (files.length > 1) selectBatch(files);
}

$('preparePdfBtn').addEventListener('click', async () => {
    const file = state.pendingFile;
    if (!file || state.selectedSource?.format !== 'pdf') return;
    window.setLoading($('preparePdfBtn'), true);
    try {
        const form = new FormData(); form.append('file', file);
        const draft = await window.api('/api/pdf-order', {method: 'POST', formData: form});
        if (state.pendingFile === file) location.assign('/pdf-order?draft=' + encodeURIComponent(draft.draft_id));
    } catch (error) {
        view.status('Не удалось подготовить структуру: ' + error.message + ' Обычная конвертация остаётся доступна.', 'error');
    } finally { window.setLoading($('preparePdfBtn'), false); }
});

function renderVisualEvidence(report) {
    const records = report?.metrics?.visual_measurements || [];
    $('visualEvidence').hidden = !records.length;
    const list = $('visualEvidenceList');
    list.replaceChildren();
    for (const record of records) {
        const item = document.createElement('li');
        const title = document.createElement('strong');
        title.textContent = `Страница ${record.page}: ` + (Number.isFinite(record.similarity)
            ? `${Math.round(record.similarity * 100)}% сходства` : 'не измерено');
        const conditions = document.createElement('span');
        const versions = Object.entries(record.versions || {}).map(([name, value]) => `${name} ${value}`).join(', ');
        conditions.textContent = `${record.source_name} → ${record.target_name} · ${record.dpi} dpi · ` +
            `${record.method} · ${new Date(record.measured_at).toLocaleString()} · ${versions}`;
        item.append(title, conditions);
        list.append(item);
    }
}

function renderReport(data, failed = false, taskId = state.activeTaskId) {
    experience.stage(2);
    const report = data.report || {issues: [], metrics: {}};
    const issues = report.issues || [];
    const losses = issues.filter((item) => item.severity === 'loss');
    const warnings = issues.filter((item) => item.severity === 'warning');
    const planned = report.metrics?.plan?.steps || [];
    const steps = planned.length ? planned.map((step) => step.description || step.id) : (report.metrics?.executed_steps || []);
    $('resultCard').hidden = false;
    state.resultTaskId = failed ? null : taskId;
    $('resultTitle').textContent = failed ? 'Конвертация требует внимания' : 'Документ готов';
    $('resultFilename').textContent = data.filename || 'Результат не создан';
    $('resultMode').textContent = Array.from($('mode').options).find(option => option.value === data.mode)?.textContent || $('mode').selectedOptions[0]?.textContent || '—';
    $('resultRoute').textContent = steps.length ? steps.join(' → ') : 'Прямое преобразование';
    const importAssessments = [data.report?.metrics?.source_import, ...Object.values(data.report?.metrics?.step_metrics || {})]
        .filter(item => typeof item?.assessment_complete === 'boolean');
    const incompleteImport = importAssessments.some(item => item.assessment_complete === false);
    $('importAssessmentSummary').hidden = !incompleteImport;
    $('importAssessmentSummary').textContent = incompleteImport
        ? 'Библиотека проверяет часть свойств документа. Отсутствие сообщений не подтверждает сохранность всех объектов.' : '';
    $('qualityBadge').className = `quality-badge ${failed ? 'bad' : !data.report || losses.length ? 'warn' : 'good'}`;
    $('qualityBadge').textContent = failed ? 'Ошибка' : !data.report ? 'Отчёт о качестве недоступен' : losses.length ? `Сообщений о потерях: ${losses.length}` : warnings.length ? `Замечания: ${warnings.length}` : 'Потерь не зарегистрировано';
    renderQualityGate($, report);
    renderObjectGate($, report);
    renderTextGate($, report);
    renderFormulaGate($, report);
    renderEmphasisGate($, report);
    renderHeadingGate($, report);
    renderPdfVectors($, report);
    renderTargetChecks($, report);
    renderIssues($, report);
    $('htmlSemanticsNotice').hidden = failed || data.target_format !== 'html';
    renderVisualEvidence(report);
    view.comparison(data.comparison, data.inspection_error);
    preview.init(failed ? null : taskId);
    $('downloadBtn').hidden = failed;
    $('resultCard').scrollIntoView({behavior: 'smooth', block: 'start'});
}

const preview = createPreviewController($, (data, taskId) => {
    renderReport(data, false, taskId);
}, renderVisualEvidence);

async function pollTask(url) {
    try {
        const data = await conversionApi.taskStatus(url);
        if (data.status === 'done') {
            view.progress(true, 100, 'Готово');
            renderReport(data);
            view.busy(false);
            window.setLoading($('convertBtn'), false);
            setTimeout(() => view.progress(false, 0, ''), 500);
        } else if (['error', 'interrupted', 'cancelled', 'expired'].includes(data.status)) {
            view.progress(false, 0, '');
            view.busy(false);
            window.setLoading($('convertBtn'), false);
            const reason = {cancelled: 'Задача отменена', expired: 'Истёк срок хранения задачи', interrupted: 'Задача прервана перезапуском сервера'};
            view.status(data.error ? `Не удалось конвертировать: ${data.error}` : reason[data.status] || 'Конвертация завершилась с ошибкой', 'error');
            if (data.report) renderReport(data, true);
        } else {
            view.progress(true, 70, 'Конвертация и проверка результата…');
            setTimeout(() => pollTask(url), 900);
        }
    } catch (error) { view.progress(false, 0, ''); view.busy(false); window.setLoading($('convertBtn'), false); view.status(error.message || 'Не удалось получить статус. Проверьте список «Задачи».', 'error'); }
}

async function pollJob(jobId, version = ++batchPollVersion) {
    if (version !== batchPollVersion) return;
    $('batchArchiveBtn').hidden = true;
    $('batchCancelBtn').hidden = true;
    try {
        const data = await conversionApi.job(jobId);
        if (version !== batchPollVersion) return;
        batchFilter.update(jobId, data.tasks);
        $('batchCancelBtn').hidden = !data.tasks.some((task) => ['queued', 'running'].includes(task.status));
        $('batchCancelBtn').onclick = () => history.cancel(jobId, $('batchCancelBtn'));
        if (data.tasks.some((task) => ['queued', 'running', 'cancelling'].includes(task.status))) {
            $('batchProgressState').textContent = data.tasks.some((task) => task.status === 'cancelling')
                ? 'Отменяем…' : 'Конвертируем…';
            setTimeout(() => pollJob(jobId, version), 900);
        } else {
            $('batchProgressState').textContent = 'Готово';
            $('batchArchiveBtn').hidden = !data.tasks.some((task) => task.status === 'done');
            $('batchArchiveBtn').onclick = () => downloadResult(
                `/api/convert/jobs/${encodeURIComponent(jobId)}/archive`, 'converted-batch.zip');
            history.load();
        }
    } catch (_) {
        if (version === batchPollVersion) $('batchProgressState').textContent = 'Не удалось получить статус';
    }
}

history = createHistoryController($, {openPreview: preview.open, pollJob});

async function startSingle() {
    if ($('conversionWorkspace').dataset.processing === 'true') return;
    const target = selectedTarget();
    if (!state.pendingFile || !state.selectedSource || !target) return;
    if (!$('maxChangedFormulas').reportValidity() || !$('maxChangedEmphasis').reportValidity() || !$('maxChangedHeadings').reportValidity()) return;
    if ($('textPreservation').value === 'flow' && !$('maxTextEdits').reportValidity()) return;
    $('resultCard').hidden = true;
    view.status('');
    view.progress(true, 20, 'Загрузка документа…');
    view.busy(true);
    window.setLoading($('convertBtn'), true);
    try {
        state.activeTask = await conversionApi.start(
            state.pendingFile, target.format, $('mode').value, $('minRetention').value,
            $('maxLossIssues').value, $('maxLostObjects').value, false, $('textPreservation').value,
            $('textPreservation').value === 'flow' ? $('maxTextEdits').value : '', $('maxChangedFormulas').value, $('maxChangedEmphasis').value, $('maxChangedHeadings').value, $('txtEncoding').value);
        state.activeTaskId = state.activeTask.task_id;
        view.progress(true, 45, 'Анализ структуры и выбор маршрута…');
        pollTask(state.activeTask.status);
    } catch (error) { view.progress(false, 0, ''); view.busy(false); window.setLoading($('convertBtn'), false); view.status(error.message || 'Не удалось запустить конвертацию. Файл и настройки сохранены — повторите запуск.', 'error'); }
}

async function startBatch() {
    if ($('conversionWorkspace').dataset.processing === 'true') return;
    const target = selectedTarget();
    if (!state.batchFiles || !target) return;
    if (!$('maxChangedFormulas').reportValidity() || !$('maxChangedEmphasis').reportValidity() || !$('maxChangedHeadings').reportValidity()) return;
    if ($('textPreservation').value === 'flow' && !$('maxTextEdits').reportValidity()) return;
    view.status('');
    $('batchConvertBtn').hidden = true;
    view.busy(true);
    try {
        const job = await conversionApi.startBatch(
            state.batchFiles, target.format, $('mode').value, $('minRetention').value,
            $('maxLossIssues').value, $('maxLostObjects').value, false, $('textPreservation').value,
            $('textPreservation').value === 'flow' ? $('maxTextEdits').value : '', batchOptions.values(), $('maxChangedFormulas').value, $('maxChangedEmphasis').value, $('maxChangedHeadings').value, $('txtEncoding').value);
        $('batchProgressCard').hidden = false;
        $('batchProgressState').textContent = 'Конвертируем…';
        $('batchProgressCard').scrollIntoView({behavior: 'smooth', block: 'start'});
        pollJob(job.job_id);
    } catch (error) { $('batchConvertBtn').hidden = false; view.status(error.message || 'Не удалось запустить пакет. Файлы и настройки сохранены — повторите запуск.', 'error'); }
    finally { view.busy(false); }
}

function bindUpload() {
    const drop = $('dropZone');
    drop.addEventListener('click', () => { if ($('conversionWorkspace').dataset.processing !== 'true') $('fileInput').click(); });
    drop.addEventListener('keydown', (event) => {
        if ($('conversionWorkspace').dataset.processing !== 'true' && ['Enter', ' '].includes(event.key)) { event.preventDefault(); $('fileInput').click(); }
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
    $('downloadBtn').addEventListener('click', () => state.resultTaskId && downloadResult('/api/convert/result/' + encodeURIComponent(state.resultTaskId), $('resultFilename').textContent));
    $('anotherBtn').addEventListener('click', () => {
        experience.stage(0);
        $('resultCard').hidden = true;
        $('conversionSetup').hidden = true;
        $('filePickerWrap').hidden = false;
        view.status('');
        $('fileInput').value = '';
        Object.assign(state, {pendingFile: null, selectedSource: null, batchFiles: null, batchTargets: null, activeTaskId: null});
        state.inspectionRequest += 1;
        preview.reset();
        $('dropZone').scrollIntoView({behavior: 'smooth', block: 'center'});
    });
    history.load();
    try {
        state.capabilities = await conversionApi.capabilities();
        renderCatalog($('formatCatalogContent'), state.capabilities);
        const extensions = state.capabilities.sources.flatMap((source) => source.extensions);
        $('fileInput').accept = extensions.join(',');
        $('drop-hint').textContent = extensions.map((item) => item.slice(1).toUpperCase()).join(', ') +
            ' · формат определится автоматически · можно выбрать несколько файлов';
    } catch (_) {
        $('drop-hint').textContent = 'Не удалось получить список доступных форматов';
        $('formatCatalogContent').textContent = 'Не удалось загрузить направления. Обновите страницу, чтобы повторить попытку.';
    }
}

init();
