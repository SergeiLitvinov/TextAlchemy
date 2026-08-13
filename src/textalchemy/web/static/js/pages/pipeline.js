"use strict";

import {pipelineApi} from './pipeline/api.js';
import {createStepEditor} from './pipeline/editor.js';
import {createOperationPalette} from './pipeline/palette.js';
import {specificationJson} from './pipeline/spec.js';
import {createPipelineState} from './pipeline/state.js';

const $ = (id) => document.getElementById(id);
const model = createPipelineState();
let expertDirty = false;

function status(message, type = 'info', element = $('status')) {
    if (!element) return;
    element.hidden = !message;
    element.className = `status-bar ${type}`;
    element.textContent = message || '';
}

const editor = createStepEditor($, model, () => { expertDirty = true; });
const palette = createOperationPalette($, model, (operationId) => {
    model.addStep(operationId);
    editor.render();
    expertDirty = true;
});

function setMode(mode) {
    const visual = mode === 'visual';
    $('modeVisualBtn').classList.toggle('active', visual);
    $('modeExpertBtn').classList.toggle('active', !visual);
    $('modeVisualBtn').setAttribute('aria-selected', visual);
    $('modeExpertBtn').setAttribute('aria-selected', !visual);
    $('visualMode').hidden = !visual;
    $('expertMode').hidden = visual;
    if (!visual && expertDirty) syncToExpert();
}

async function syncToExpert() {
    try {
        const json = specificationJson(model.state);
        const response = await pipelineApi.toYaml(json);
        if (!response.success) throw new Error(response.error || 'Не удалось создать YAML');
        $('specText').value = response.yaml || json;
        expertDirty = false;
    } catch (error) {
        window.toast(error.message, 'error');
    }
}

async function syncToVisual() {
    const text = $('specText').value.trim();
    if (!text) return void window.toast('Спецификация пуста', 'warning');
    try {
        const response = await pipelineApi.parse(text);
        if (!response.success) throw new Error(response.error || 'Не удалось разобрать YAML/JSON');
        model.importSpec(response.spec);
        $('ctxText').value = model.state.contextJson;
        editor.render();
        expertDirty = false;
        setMode('visual');
    } catch (error) {
        status(`Не удалось перенести спецификацию: ${error.message}`, 'error', $('statusExpert'));
    }
}

function showResult(response, element) {
    $('pipeline-result').hidden = false;
    $('result-output').textContent = JSON.stringify(response, null, 2);
    status(response.success ? 'Пайплайн завершён.' : 'Пайплайн завершился с ошибкой.', response.success ? 'success' : 'error', element);
}

async function run(specification, button, element = $('status')) {
    window.setLoading(button, true);
    status('Запуск пайплайна…', 'info', element);
    try {
        const response = await pipelineApi.run(specification);
        showResult(response, element);
        window.toast(response.success ? 'Пайплайн завершён' : 'Пайплайн завершился с ошибкой', response.success ? 'success' : 'error');
    } catch (error) {
        status(`Ошибка запуска: ${error.message}`, 'error', element);
    } finally {
        window.setLoading(button, false);
    }
}

async function validate() {
    let json;
    try { json = specificationJson(model.state); }
    catch (error) { return void window.toast(error.message, 'error'); }
    window.setLoading($('validateBtn'), true);
    try {
        const response = await pipelineApi.validate(json);
        if (response.success) {
            const warnings = response.warnings?.length ? ` Предупреждения: ${response.warnings.join('; ')}` : '';
            status(`Связи в порядке.${warnings}`, 'success');
            window.toast('Пайплайн валиден', 'success');
        } else {
            const errors = response.errors.map((error) =>
                `${error.step === null || error.step === undefined ? '' : `шаг ${error.step}: `}${error.message}`,
            );
            status(`Найдены ошибки: ${errors.join('; ')}`, 'error');
        }
    } catch (error) {
        status(`Ошибка проверки: ${error.message}`, 'error');
    } finally {
        window.setLoading($('validateBtn'), false);
    }
}

function bindActions() {
    $('modeVisualBtn').addEventListener('click', () => setMode('visual'));
    $('modeExpertBtn').addEventListener('click', () => setMode('expert'));
    $('toBuilderBtn').addEventListener('click', syncToVisual);
    $('addStepBtn').addEventListener('click', () => {
        if (!model.state.operations.length) return void window.toast('Список операций пуст', 'error');
        model.addStep(model.state.operations[0].id);
        editor.render();
        expertDirty = true;
    });
    $('validateBtn').addEventListener('click', validate);
    $('runBtn').addEventListener('click', () => {
        try { run(specificationJson(model.state), $('runBtn')); }
        catch (error) { window.toast(error.message, 'error'); }
    });
    $('expertRunBtn').addEventListener('click', () => {
        const text = $('specText').value.trim();
        if (text) run(text, $('expertRunBtn'), $('statusExpert'));
        else window.toast('Спецификация пуста', 'warning');
    });
}

async function init() {
    bindActions();
    try {
        model.setOperations(await pipelineApi.operations());
        model.defaultSteps();
        palette.render();
        editor.render();
        expertDirty = true;
    } catch (_) {
        $('opsPalette').innerHTML = '<p class="hint">Не удалось загрузить операции.</p>';
    }
}

init();
