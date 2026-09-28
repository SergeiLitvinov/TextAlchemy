"use strict";
const [{createGeneratorDraft}, {createGeneratorDatasets}, {createTemplateVariables}, {createTemplateConditions}, {createTemplateLoops}, {createGeneratorWorkspace}, {createListEditor}, {createGeneratedPreview}, {createTemplateSource}, {createRichEditor}] = await Promise.all([
    './generator-draft.js',
    './generator-datasets.js',
    './template-variables.js',
    './template-conditions.js',
    './template-loops.js',
    './generator-workspace.js',
    './generator-list.js',
    './generator-preview.js',
    './template-source.js',
    './template-rich.js'
].map(path => import(path + new URL(import.meta.url).search)));

const $ = (id) => document.getElementById(id);
const TYPE_LABELS = {
    string: 'текст', integer: 'целое число', number: 'число', boolean: 'да/нет',
    array: 'список', object: 'объект (JSON)', image: 'изображение', formula: 'формула (LaTeX или MathML)', any: 'любой'
};
const FIELD_LABELS = {
    author: 'Автор', body: 'Основной текст', title: 'Заголовок', abstract: 'Аннотация',
    date: 'Дата', organization: 'Организация', bibliography: 'Список литературы', items: 'Список значений',
};
const SCHEMA_SOURCE_LABELS = {
    derived: 'поля определены автоматически', sidecar: 'проверяемая схема шаблона',
};
let currentSchema = null;
let previewState = null;
let schemaRequest = 0;
let loadedTemplate = '';
const draft = createGeneratorDraft($);
const workspace = createGeneratorWorkspace($);
const imageReads = new Set();
const listEditors = new Map();
const generatedPreview = createGeneratedPreview($, () => imageReads.size || workspace.isEditing() ? null : collectParams(true), renderErrors);
const sourceEditor = createTemplateSource($, useTemplateCopy, () => $('editMode').click());
const richEditor = createRichEditor($, useTemplateCopy);
async function useTemplateCopy(name) {
    $('template').appendChild(new Option('Изменённый шаблон — ' + name.slice(-8), name));
    if (!draft.canSwitch()) return;
    $('template').value = name;
    const loading = loadTemplate(name);
    workspace.finish();
    await loading;
}
const variables = createTemplateVariables($, useTemplateCopy);
const conditions = createTemplateConditions($, useTemplateCopy);
const loops = createTemplateLoops($, useTemplateCopy);
const rowLoops = createTemplateLoops($, useTemplateCopy, true);
const datasets = createGeneratorDatasets($, () => {
    if (imageReads.size) throw new Error('Дождитесь чтения изображений.');
    return draft.snapshot();
}, snapshot => {
    const restored = draft.begin(loadedTemplate, currentSchema, snapshot);
    listEditors.forEach(editor => editor.refresh());
    if (restored) { clearFieldErrors(); saveDraft(); }
    return restored;
});

function saveDraft() {
    generatedPreview.invalidate();
    draft.save();
    if (imageReads.size) draft.pendingImage();
}

function setStatus(msg, type) {
    const el = $('status');
    el.hidden = !msg;
    if (!msg) return;
    el.className = 'status-bar ' + (type || 'info');
    el.textContent = msg;
}

function fieldErrorId(name) {
    return 'field-error-' + name.replace(/[^A-Za-z0-9_-]/g, '-');
}

function fieldLabel(name) {
    const field = currentSchema?.fields.find(item => item.name === name);
    if (name.startsWith('field_') && field?.description) return field.description;
    if (FIELD_LABELS[name]) return FIELD_LABELS[name];
    const readable = name.replace(/[_-]+/g, ' ').trim();
    return readable ? readable.charAt(0).toUpperCase() + readable.slice(1) : name;
}

function buildField(field) {
    const type = field.type || 'any';
    const name = field.name;
    const required = Boolean(field.required);
    const def = field.hasOwnProperty('default') ? field.default : '';
    const wrap = document.createElement('div');
    wrap.className = 'form-group';
    wrap.dataset.fieldName = name;

    const label = document.createElement('label');
    label.setAttribute('for', 'field-' + name);
    label.textContent = fieldLabel(name) + (required ? ' *' : '');
    const hint = document.createElement('span');
    hint.className = 'field-help';
    hint.textContent = ' — ' + ((!name.startsWith('field_') && field.description) || TYPE_LABELS[type] || type);
    label.appendChild(hint);
    wrap.appendChild(label);

    let input;
    if (type === 'boolean') {
        input = document.createElement('input');
        input.type = 'checkbox';
        input.id = 'field-' + name;
        input.checked = Boolean(def);
    } else if (type === 'integer' || type === 'number') {
        input = document.createElement('input');
        input.type = 'number';
        input.id = 'field-' + name;
        if (type === 'integer') input.step = '1';
        if (def !== '' && def !== undefined && def !== null) input.value = def;
    } else if (type === 'array' || type === 'object') {
        input = document.createElement('textarea');
        input.id = 'field-' + name;
        input.rows = 3;
        input.placeholder = type === 'array' ? '[ "item1", "item2" ]' : '{ "key": "value" }';
        if (def !== '' && def !== undefined && def !== null) input.value = JSON.stringify(def, null, 2);
    } else if (type === 'image') {
        input = document.createElement('input');
        input.type = 'file';
        input.id = 'field-' + name;
        input.accept = 'image/*';
        input.dataset.imageField = name;
    } else if (type === 'formula') {
        input = document.createElement('textarea');
        input.id = 'field-' + name;
        input.rows = 2;
        input.placeholder = 'E = mc^2';
        if (def !== '' && def !== undefined && def !== null) input.value = def;
    } else if (type === 'string' && ['body', 'abstract'].includes(name)) {
        input = document.createElement('textarea');
        input.id = 'field-' + name;
        input.rows = name === 'body' ? 6 : 3;
        if (def !== '' && def !== undefined && def !== null) input.value = def;
    } else {
        input = document.createElement('input');
        input.type = 'text';
        input.id = 'field-' + name;
        if (def !== '' && def !== undefined && def !== null) input.value = def;
    }

    const error = document.createElement('p');
    error.className = 'field-help';
    error.id = fieldErrorId(name);
    error.style.color = '#991b1b';
    error.style.display = 'none';
    wrap.appendChild(input);
    if (type === 'array') listEditors.set(name, createListEditor(input, fieldLabel(name)));
    wrap.appendChild(error);
    return wrap;
}

function collectParams(preview = false) {
    const params = {};
    if (!currentSchema) return params;
    for (const field of currentSchema.fields) {
        const name = field.name;
        const input = $('field-' + name);
        if (!input) continue;
        const type = field.type || 'any';
        if (preview && type !== 'boolean' && !(type === 'image' ? input.dataset.imageData : input.value.trim())) {
            params[name] = ''; continue;
        }
        let value;
        if (type === 'boolean') {
            value = input.checked;
        } else if (type === 'integer' || type === 'number') {
            if (input.value === '') continue;
            value = type === 'integer' ? parseInt(input.value, 10) : parseFloat(input.value);
        } else if (type === 'array' || type === 'object') {
            if (!input.value.trim()) continue;
            try {
                value = JSON.parse(input.value);
            } catch (err) {
                if (!preview) toast('Поле «' + name + '»: некорректный JSON', 'error');
                showFieldError(name, 'некорректный JSON: ' + err.message);
                return null;
            }
        } else if (type === 'image') {
            if (input.dataset.imageData) {
                value = input.dataset.imageData;
            } else {
                continue;
            }
        } else {
            value = input.value;
        }
        if (value !== undefined && value !== '') params[name] = value;
    }
    return params;
}

function clearFieldErrors() {
    document.querySelectorAll('[id^="field-error-"]').forEach((el) => { el.style.display = 'none'; });
}

function showFieldError(name, message) {
    const el = $(fieldErrorId(name));
    if (!el) return;
    el.textContent = message;
    el.style.display = 'block';
}

function renderErrors(errors) {
    clearFieldErrors();
    if (!errors) return;
    for (const [name, message] of Object.entries(errors)) {
        showFieldError(name, message);
    }
}

async function loadTemplates() {
    try {
        const templates = await api('/api/generate/templates');
        const sel = $('template');
        for (const t of templates) {
            const opt = document.createElement('option');
            opt.value = t.name;
            opt.textContent = t.description || t.name;
            sel.appendChild(opt);
        }
        if (templates.length) {
            sel.value = draft.initial(templates.map(template => template.name));
            await loadTemplate(sel.value);
        }
    } catch (_) { /* toast уже показан */ }
}

async function loadTemplate(name) {
    generatedPreview.reset();
    const request = ++schemaRequest;
    draft.pause();
    datasets.bind(null);
    variables.bind(null);
    conditions.bind(null);
    loops.bind(null);
    rowLoops.bind(null);
    sourceEditor.bind(null);
    richEditor.bind(null);
    imageReads.clear();
    listEditors.clear();
    $('genBtn').disabled = true;
    currentSchema = null;
    previewState = null;
    $('fieldsContainer').innerHTML = '';
    $('previewPaging').hidden = true;
    $('previewCanvas').textContent = 'Загружаем страницы шаблона…';
    $('templateDesc').textContent = '';
    try {
        const data = await api('/api/generate/templates/' + encodeURIComponent(name) + '/schema');
        if (request !== schemaRequest) return;
        currentSchema = data.schema;
        loadedTemplate = name;
        $('templateDesc').textContent = data.description + ' · ' + (SCHEMA_SOURCE_LABELS[data.source] || data.source);
        const container = $('fieldsContainer');
        const first = ['title', 'author', 'abstract', 'body'];
        const rank = field => first.includes(field.name) ? first.indexOf(field.name) : first.length;
        for (const field of [...currentSchema.fields].sort((a, b) => rank(a) - rank(b))) {
            const wrap = buildField(field);
            container.appendChild(wrap);
            const input = wrap.querySelector('input[type="file"]');
            if (input) {
                input.addEventListener('change', (e) => {
                    generatedPreview.invalidate();
                    input.parentElement.querySelector('[data-restored-image]')?.remove();
                    const file = e.target.files && e.target.files[0];
                    if (!file) {
                        imageReads.delete(input); input.dataset.imageData = '';
                        $('genBtn').disabled = imageReads.size > 0; saveDraft(); return;
                    }
                    imageReads.add(input);
                    draft.pendingImage(); $('genBtn').disabled = true;
                    const reader = new FileReader();
                    reader.onload = () => {
                        if (request !== schemaRequest || input.files[0] !== file) return;
                        imageReads.delete(input); input.dataset.imageData = reader.result;
                        $('genBtn').disabled = imageReads.size > 0; saveDraft();
                    };
                    reader.onerror = () => { if (request === schemaRequest) draft.imageError(); };
                    reader.readAsDataURL(file);
                });
            }
        }
        if (!currentSchema.fields.length) {
            const empty = document.createElement('p');
            empty.className = 'field-help';
            empty.textContent = 'У шаблона нет параметров.';
            container.appendChild(empty);
        }
        draft.begin(name, currentSchema);
        listEditors.forEach(editor => editor.refresh());
        datasets.bind(name);
        variables.bind(name);
        conditions.bind(name);
        loops.bind(name);
        rowLoops.bind(name);
        sourceEditor.bind(name);
        richEditor.bind(name);
        $('genBtn').disabled = false;
        generatedPreview.ready();
        await loadPreviewMeta(name, request);
    } catch (_) { /* toast уже показан */ }
}

async function loadPreviewMeta(name, request) {
    try {
        const meta = await api('/api/generate/templates/' + encodeURIComponent(name) + '/preview/meta');
        if (request !== schemaRequest) return;
        if (!meta.available || meta.pages < 1) {
            $('previewCanvas').textContent = 'Просмотр страниц недоступен. Вы можете заполнить поля и скачать документ.';
            return;
        }
        previewState = { name, pages: meta.pages, page: 1 };
        $('previewPaging').hidden = !$('filledPreview').hidden;
        renderPreview();
    } catch (_) {
        if (request === schemaRequest) $('previewCanvas').textContent = 'Не удалось загрузить страницы. Заполнение и скачивание доступны.';
    }
}

function renderPreview() {
    if (!previewState) return;
    const canvas = $('previewCanvas');
    $('previewPageLabel').textContent = previewState.page + ' / ' + previewState.pages;
    canvas.innerHTML = '<figure><img src="/api/generate/templates/' + encodeURIComponent(previewState.name) +
        '/preview?page=' + previewState.page + '&dpi=110" alt="Страница ' + previewState.page + '"></figure>';
    $('previewPrev').disabled = previewState.page <= 1;
    $('previewNext').disabled = previewState.page >= previewState.pages;
}

function updateFormatButtons() {
    const format = $('formatGroup').querySelector('.format-option.active').dataset.format;
    const out = $('output');
    const stem = out.value.replace(/\.(docx|pdf|html)$/i, '') || 'output';
    out.value = stem + '.' + format;
}

$('formatGroup').addEventListener('click', (e) => {
    const btn = e.target.closest('.format-option');
    if (!btn || btn.disabled) return;
    $('formatGroup').querySelectorAll('.format-option').forEach((b) => b.classList.toggle('active', b === btn));
    updateFormatButtons();
    saveDraft();
});

$('previewPrev').addEventListener('click', () => {
    if (previewState && previewState.page > 1) { previewState.page -= 1; renderPreview(); }
});
$('previewNext').addEventListener('click', () => {
    if (previewState && previewState.page < previewState.pages) { previewState.page += 1; renderPreview(); }
});
$('previewCanvas').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') $('previewPrev').click();
    if (e.key === 'ArrowRight') $('previewNext').click();
});

$('generate-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (workspace.isEditing()) return;
    clearFieldErrors();
    const template = $('template').value;
    if (!template) { toast('Выберите шаблон', 'error'); return; }
    const output = $('output').value || 'output.docx';
    const format = $('formatGroup').querySelector('.format-option.active').dataset.format;
    const params = collectParams();
    if (params === null) return;
    const fd = new FormData();
    fd.set('template', template);
    fd.set('output', output);
    fd.set('format', format);
    fd.set('params', JSON.stringify(params));
    const btn = $('genBtn');
    setLoading(btn, true);
    setStatus('Генерация…', 'info');
    try {
        const res = await fetch('/api/generate', { method: 'POST', body: fd });
        const ct = res.headers.get('Content-Type') || '';
        if (ct.includes('application/json')) {
            const data = await res.json();
            renderErrors(data.errors);
            setStatus('Ошибка: ' + (data.error || 'неизвестно'), 'error');
        } else if (res.ok) {
            const blob = await res.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = output;
            a.click();
            URL.revokeObjectURL(a.href);
            setStatus('Документ сгенерирован и загружен.', 'success');
            toast('Документ готов', 'success');
        } else {
            setStatus('Ошибка генерации', 'error');
        }
    } catch (err) {
        setStatus('Ошибка сети: ' + err.message, 'error');
    } finally {
        setLoading(btn, false);
    }
});

$('template').addEventListener('change', () => {
    if (!draft.canSwitch()) { $('template').value = loadedTemplate; return; }
    if ($('template').value) loadTemplate($('template').value);
});
$('fieldsContainer').addEventListener('input', event => { if (event.target.type !== 'file') saveDraft(); });
$('output').addEventListener('input', () => saveDraft());
$('restoreDraft').addEventListener('click', () => {
    if (draft.restore()) {
        listEditors.forEach(editor => editor.refresh());
        clearFieldErrors(); generatedPreview.invalidate();
    }
});
$('fillMode').addEventListener('click', () => generatedPreview.invalidate());
$('editMode').addEventListener('click', () => generatedPreview.invalidate());
$('clearDraft').addEventListener('click', () => {
    if (draft.forget()) loadTemplate(loadedTemplate);
});
loadTemplates();
