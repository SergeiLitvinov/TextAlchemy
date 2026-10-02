"use strict";

const [{pipelineApi}, {createStepEditor}, {createOperationPalette}, {specificationJson},
    {createPipelineState}, {renderPipelineResult}] = await Promise.all(
    ['api', 'editor', 'palette', 'spec', 'state', 'results'].map(name => import(`./pipeline/${name}.js` + new URL(import.meta.url).search)));

const $ = id => document.getElementById(id);
const model = createPipelineState();
const disabled = new Map();
let expertDirty = false;
let working = false;
let revision = 0;
let resultRevision = null;

function status(message, type = 'info', element = $('status')) {
    element.hidden = !message;
    element.className = `status-bar ${type}`;
    element.textContent = message || '';
}
function lock(value) {
    working = value;
    if (value) {
        document.querySelectorAll('#visualMode input, #visualMode select, #visualMode textarea, #visualMode button, #expertMode textarea, #expertMode button, #modeVisualBtn, #modeExpertBtn').forEach(control => {
            disabled.set(control, control.disabled);
            control.disabled = true;
        });
    } else {
        for (const [control, previous] of disabled) control.disabled = previous;
        disabled.clear();
    }
}
function changed(visual = true) {
    revision++;
    if (visual) expertDirty = true;
    status('Сценарий изменён. Проверьте связи перед запуском.');
    status('Текст изменён. Для проверки в конструкторе переключите режим.', 'info', $('statusExpert'));
    if (resultRevision !== null) {
        $('resultVersionNote').hidden = false;
        $('resultVersionNote').textContent = 'Ниже результат предыдущего запуска. Изменённый сценарий ещё не выполнен.';
    }
}
const editor = createStepEditor($, model, changed, lock);
const palette = createOperationPalette($, model, operationId => {
    if (working) return;
    model.addStep(operationId);
    editor.render();
    changed();
    $('operationCatalog').open = false;
    $('stepsList').lastElementChild?.scrollIntoView({block: 'center', behavior: 'smooth'});
});
function displayMode(visual) {
    $('modeVisualBtn').classList.toggle('active', visual);
    $('modeExpertBtn').classList.toggle('active', !visual);
    $('modeVisualBtn').setAttribute('aria-selected', String(visual));
    $('modeExpertBtn').setAttribute('aria-selected', String(!visual));
    $('visualMode').hidden = !visual;
    $('expertMode').hidden = visual;
}
async function toExpert() {
    if (working) return;
    if (!expertDirty) { displayMode(false); return; }
    let json;
    try { json = specificationJson(model.state); }
    catch (error) { status(error.message, 'error'); return; }
    lock(true);
    try {
        const response = await pipelineApi.toYaml(json);
        if (!response.success) throw new Error(response.error || 'Не удалось создать YAML');
        $('specText').value = response.yaml || json;
        status('', 'info', $('statusExpert'));
    } catch (error) {
        $('specText').value = json;
        status(`YAML недоступен: ${error.message}. Правки перенесены в JSON.`, 'info', $('statusExpert'));
    } finally {
        expertDirty = false;
        displayMode(false);
        lock(false);
    }
}
async function toVisual() {
    if (working || $('expertMode').hidden) return;
    const text = $('specText').value.trim();
    if (!text) return status('Введите YAML или JSON сценария.', 'error', $('statusExpert'));
    lock(true);
    try {
        const response = await pipelineApi.parse(text);
        if (!response.success) throw new Error(response.error || 'Не удалось разобрать YAML/JSON');
        model.importSpec(response.spec);
        $('ctxText').value = model.state.contextJson;
        $('customOutput').value = '';
        editor.render();
        expertDirty = false;
        displayMode(true);
        status('Правки из текста перенесены. Проверьте связи перед запуском.');
    } catch (error) {
        status(`Не удалось перенести: ${error.message}. Текст сохранён.`, 'error', $('statusExpert'));
    } finally { lock(false); }
}
function showResult(response, element) {
    const success = renderPipelineResult($, response);
    resultRevision = revision;
    $('resultVersionNote').hidden = true;
    status(success ? 'Сценарий выполнен.' : 'Сценарий завершился с ошибкой.', success ? 'success' : 'error', element);
}
async function run(specification, button, element = $('status')) {
    if (working) return;
    lock(true);
    window.setLoading(button, true);
    status('Выполняем сценарий…', 'info', element);
    try { showResult(await pipelineApi.run(specification), element); }
    catch (error) { showResult({success: false, error: `Ошибка запуска: ${error.message}`}, element); }
    finally { window.setLoading(button, false); lock(false); }
}
async function validate() {
    if (working) return;
    let json;
    try { json = specificationJson(model.state); }
    catch (error) { return status(error.message, 'error'); }
    lock(true);
    window.setLoading($('validateBtn'), true);
    try {
        const response = await pipelineApi.validate(json);
        if (response.success) {
            const warnings = response.warnings?.length ? ` Предупреждения: ${response.warnings.join('; ')}` : '';
            status(`Связи в порядке.${warnings} Сценарий не выполнялся; доступность файлов и качество результата не проверены.`, 'success');
        } else {
            const errors = (response.errors || []).map(error => `${error.step == null ? '' : `шаг ${error.step + 1}: `}${error.message}`);
            status(`Найдены ошибки: ${errors.join('; ')}`, 'error');
        }
    } catch (error) { status(`Ошибка проверки: ${error.message}`, 'error'); }
    finally { window.setLoading($('validateBtn'), false); lock(false); }
}
$('modeVisualBtn').addEventListener('click', toVisual);
$('modeExpertBtn').addEventListener('click', toExpert);
$('specText').addEventListener('input', () => changed(false));
$('addStepBtn').addEventListener('click', () => {
    if (working) return;
    $('operationCatalog').open = true;
    $('opSearch').focus();
    $('opSearch').scrollIntoView({block: 'center', behavior: 'smooth'});
});
$('validateBtn').addEventListener('click', validate);
$('runBtn').addEventListener('click', () => {
    try { run(specificationJson(model.state), $('runBtn')); }
    catch (error) { status(error.message, 'error'); }
});
$('expertRunBtn').addEventListener('click', () => {
    const text = $('specText').value.trim();
    if (text) run(text, $('expertRunBtn'), $('statusExpert'));
    else status('Введите YAML или JSON сценария.', 'error', $('statusExpert'));
});
async function init() {
    lock(true);
    try {
        model.setOperations(await pipelineApi.operations());
        model.defaultSteps();
        palette.render();
        editor.render();
        expertDirty = true;
    } catch (error) { status(`Не удалось загрузить действия: ${error.message}. Обновите страницу.`, 'error'); }
    finally { lock(false); }
}
init();
