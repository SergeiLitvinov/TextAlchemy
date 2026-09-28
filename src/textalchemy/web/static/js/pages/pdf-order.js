"use strict";
import {createTableBounds} from './pdf-table-bounds.js';
import {createPdfDiagnostics} from './pdf-diagnostics.js';
const $ = id => document.getElementById(id);
let draft = null, dirty = false, busy = false;
let classifications = {};
const status = message => { $('orderStatus').textContent = message; };
const endpoint = () => '/api/pdf-order/' + encodeURIComponent(draft.draft_id);
const blocks = () => draft.pages[Number($('orderPage').value)].blocks;
const tableBounds = createTableBounds($, () => { dirty = true; controls(); });
const diagnostics = createPdfDiagnostics($, (target, message) => {
    if (busy || dirty || !selectBlock(target.block_id)) return;
    const url = new URL(location.href); url.searchParams.set('block', target.block_id);
    history.replaceState(null, '', url);
    status(message + ' Выбран содержащий проблему блок исходного PDF.');
    $('orderBlocks').focus({preventScroll: true});
    $('orderImage').scrollIntoView({behavior: 'smooth', block: 'center'});
});

function selectBlock(id) {
    const page = draft.pages.findIndex(page => page.blocks.some(block => block.id === id));
    if (page < 0) return false;
    $('orderPage').value = String(page); showPage();
    $('orderBlocks').value = id; highlight(); return true;
}

function controls() {
    if (dirty) diagnostics.clear();
    $('orderCheck').disabled = busy;
    tableBounds.disable(busy);
    $('orderHotspots').querySelectorAll('button').forEach(button => { button.disabled = busy; });
    for (const id of ['orderFile', 'orderPage', 'orderBlocks', 'orderFormat', 'orderReload', 'orderExport']) {
        $(id).disabled = busy;
    }
    $('orderSave').disabled = busy || !dirty;
    const selected = $('orderBlocks').selectedIndex;
    $('orderUp').disabled = busy || selected <= 0;
    $('orderDown').disabled = busy || selected < 0 || selected >= (draft ? blocks().length - 1 : 0);
    $('blockClassification').disabled = busy || !draft || !blocks()[selected]?.classifiable;
    $('orderDirty').textContent = dirty ? 'Есть несохранённые правки' : 'Правки сохранены';
}

function highlight() {
    $('orderHotspots').querySelectorAll('button').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.block === $('orderBlocks').value));
    });
    $('textProperties').hidden = !blocks()[$('orderBlocks').selectedIndex]?.classifiable;
    $('blockClassification').value = blocks()[$('orderBlocks').selectedIndex]?.classification || 'auto';
    const region = blocks()[$('orderBlocks').selectedIndex]?.region;
    $('orderRegion').hidden = !region;
    if (region) {
        const [x, y, width, height] = region;
        Object.assign($('orderRegion').style, {left: x + '%', top: y + '%', width: width + '%', height: height + '%'});
    }
    tableBounds.select(blocks()[$('orderBlocks').selectedIndex], draft.pages[Number($('orderPage').value)]);
    controls();
}

function renderBlocks(selected = 0) {
    $('orderBlocks').replaceChildren(...blocks().map((block, index) => new Option(`${index + 1}. ${block.label}`, block.id)));
    $('orderBlocks').selectedIndex = blocks().length ? selected : -1;
    $('orderEmpty').hidden = blocks().length > 0;
    $('orderHotspots').replaceChildren(...blocks().filter(block => block.region).map(block => {
        const button = document.createElement('button'); button.type = 'button';
        button.className = 'pdf-hotspot'; button.dataset.block = block.id;
        button.setAttribute('aria-label', `Выбрать область: ${block.label}`); button.title = block.label;
        const [x, y, width, height] = block.region;
        Object.assign(button.style, {left: x + '%', top: y + '%', width: width + '%', height: height + '%'});
        button.onclick = () => { if (!busy) { $('orderBlocks').value = block.id; highlight(); } };
        return button;
    }));
    highlight();
}

function showPage() {
    $('orderImage').src = endpoint() + '/pages/' + $('orderPage').value;
    renderBlocks();
}

function accept(data) {
    diagnostics.clear();
    const previousPage = Number($('orderPage').value || 0);
    draft = data; dirty = false; classifications = {};
    tableBounds.reset();
    $('orderEditor').hidden = false;
    $('orderPage').replaceChildren(...draft.pages.map((_, index) => new Option(String(index + 1), String(index))));
    $('orderPage').value = String(Math.min(previousPage, draft.pages.length - 1));
    const url = new URL(location.href); url.searchParams.set('draft', draft.draft_id); history.replaceState(null, '', url);
    showPage();
    const selectedBlock = url.searchParams.get('block');
    if (selectedBlock && !selectBlock(selectedBlock)) {
        url.searchParams.delete('block'); history.replaceState(null, '', url);
    }
}

async function run(action) {
    if (busy) return;
    busy = true; controls();
    try { await action(); }
    catch (error) { status(error.message || 'Не удалось выполнить действие. Правки остаются на экране.'); }
    finally { busy = false; controls(); }
}

async function save() {
    if (!dirty) return;
    accept(await window.api(endpoint(), {method: 'PUT', json: {
        revision: draft.revision, order: draft.pages.map(page => page.blocks.map(block => block.id)),
        classifications,
        table_ranges: tableBounds.changes(),
    }}));
}

function move(direction) {
    if (busy) return;
    const from = $('orderBlocks').selectedIndex, to = from + direction;
    if (from < 0 || to < 0 || to >= blocks().length) return;
    const [block] = blocks().splice(from, 1); blocks().splice(to, 0, block);
    dirty = true; renderBlocks(to); $('orderBlocks').focus();
}

$('orderUp').onclick = () => move(-1);
$('orderDown').onclick = () => move(1);
$('orderPage').onchange = showPage;
$('orderBlocks').onchange = highlight;
$('blockClassification').onchange = () => {
    const block = blocks()[$('orderBlocks').selectedIndex];
    if (busy || !block?.classifiable) return;
    block.classification = $('blockClassification').value;
    classifications[block.id] = block.classification;
    dirty = true; controls();
};
$('orderImage').onerror = () => status('Исходная страница недоступна. Сохранённый список блоков остаётся на экране.');
$('orderFile').onchange = () => {
    const file = $('orderFile').files[0];
    if (!file || (dirty && !confirm('Продолжить без сохранения изменений порядка?'))) return;
    run(async () => {
        const form = new FormData(); form.append('file', file);
        accept(await window.api('/api/pdf-order', {method: 'POST', formData: form}));
        status('PDF загружен. ' + (draft.warnings.length ? draft.warnings.join('; ') : 'Выберите страницу и блок.'));
    });
};
$('orderSave').onclick = () => run(async () => { await save(); status('Правки сохранены.'); });
$('orderCheck').onclick = () => run(async () => {
    await save();
    diagnostics.render(await window.api(endpoint() + `/diagnostics?revision=${draft.revision}`));
    status('Проверка DOCX завершена. Замечания приведены ниже.');
});
$('orderReload').onclick = () => {
    if (dirty && !confirm('Загрузить сохранённую версию и отменить локальные правки?')) return;
    run(async () => { accept(await window.api(endpoint())); status('Сохранённый порядок восстановлен.'); });
};
$('orderExport').onclick = () => run(async () => {
    await save();
    const format = $('orderFormat').value;
    if (format === 'docx') diagnostics.render(await window.api(endpoint() + `/diagnostics?revision=${draft.revision}`));
    const response = await fetch(endpoint() + `/export?revision=${draft.revision}&format=${format}`);
    if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Экспорт не удался'); }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a'); link.href = url;
    link.download = format === 'model' ? 'ordered.model.json' : 'ordered.docx'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); status('Сохранённый результат отправлен на скачивание.');
});
window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
const id = new URL(location.href).searchParams.get('draft');
if (id) run(async () => { accept(await window.api('/api/pdf-order/' + encodeURIComponent(id))); status('Порядок восстановлен.'); });
