"use strict";

const $ = id => document.getElementById(id);
const fields = ['authors', 'title', 'doc_type', 'year', 'journal', 'publisher', 'city', 'pages', 'isbn', 'doi', 'source'];
const extraFields = ['journal', 'publisher', 'city', 'pages', 'isbn', 'doi', 'source'];
const typeLabels = Object.fromEntries(Array.from($('doc_type').options).map(option => [option.value, option.textContent]));
let items = JSON.parse($('bibliographyData').textContent);
let busy = false;
let baseline;

function collectForm() {
    const data = new FormData();
    for (const name of fields) data.set(name, $(name).value);
    return data;
}
function snapshot() { return JSON.stringify(Array.from(collectForm().entries())); }
function dirty() { return snapshot() !== baseline; }
function canDiscard() { return !dirty() || confirm('Отменить несохранённые изменения карточки?'); }
function status(message, type = 'info') {
    $('libraryStatus').hidden = !message;
    $('libraryStatus').className = 'status-bar ' + type;
    $('libraryStatus').textContent = message;
}
function setBusy(value) {
    busy = value;
    document.querySelectorAll('#bibForm input, #bibForm select, #bibForm button, #bibBody button, #newItemBtn, #importForm input, #importForm button, #refreshLibraryBtn').forEach(control => { control.disabled = value; });
    if (!value) updateImportSelection();
}
function resetForm() {
    $('itemId').value = '';
    $('bibForm').reset();
    $('saveBtn').textContent = 'Добавить источник';
    $('editorTitle').textContent = 'Новый источник';
    $('sourceDetails').open = false;
    $('bibEditor').open = false;
    $('bibEditor').hidden = true;
    baseline = snapshot();
}
function openEditor(item) {
    if (busy || !canDiscard()) return;
    resetForm();
    if (item) {
        $('itemId').value = item.id;
        if (!Array.from($('doc_type').options).some(option => option.value === item.doc_type)) {
            $('doc_type').add(new Option(item.doc_type, item.doc_type));
        }
        for (const name of fields) $(name).value = name === 'authors' ? (item.authors || []).join('; ') : item[name] || '';
        $('saveBtn').textContent = 'Сохранить изменения';
        $('editorTitle').textContent = 'Редактирование: ' + (item.title || 'Без названия');
        $('sourceDetails').open = extraFields.some(name => Boolean(item[name]));
    }
    baseline = snapshot();
    $('bibEditor').hidden = false;
    $('bibEditor').open = true;
    $('title').focus();
    $('bibEditor').scrollIntoView({behavior: 'smooth', block: 'start'});
}
function renderRows() {
    const query = $('bibSearch').value.trim().toLocaleLowerCase();
    const visible = items.filter(item => [(item.authors || []).join(' '), item.title, item.year].join(' ').toLocaleLowerCase().includes(query));
    $('bibBody').innerHTML = visible.map(item => {
        const title = esc(item.title || 'Без названия');
        return `<tr data-id="${esc(item.id)}"><td><strong>${title}</strong><small>${esc((item.authors || []).join('; '))}</small></td>` +
            `<td>${esc(typeLabels[item.doc_type] || item.doc_type)}</td><td>${esc(item.year)}</td><td class="row-actions">` +
            `<button type="button" class="icon-button" data-act="edit" data-id="${esc(item.id)}" aria-label="Редактировать ${title}" ${busy ? 'disabled' : ''}>✎</button>` +
            `<button type="button" class="icon-button danger-action" data-act="delete" data-id="${esc(item.id)}" aria-label="Удалить ${title}" ${busy ? 'disabled' : ''}>×</button></td></tr>`;
    }).join('');
    $('bibCount').textContent = items.length;
    $('bibShown').textContent = query ? `Показано: ${visible.length}` : '';
    $('bibEmpty').hidden = visible.length !== 0;
    $('bibEmpty').innerHTML = items.length
        ? '<p><strong>По этому запросу ничего не найдено</strong><small>Измените автора, название или год.</small></p>'
        : '<p><strong>Библиотека пуста</strong><small>Добавьте источник или импортируйте список.</small></p>';
}
function updateImportSelection() {
    const file = $('importFile').files[0];
    $('importSelection').textContent = file ? `Выбран: ${file.name}` : 'Файл не выбран.';
    $('importBtn').disabled = busy || !file;
    $('cancelImportBtn').hidden = !file;
}
async function refresh() {
    items = await api('/api/bibliography');
    renderRows();
}

$('bibForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const id = $('itemId').value;
    const data = collectForm();
    setBusy(true);
    status('Сохраняем карточку…');
    try {
        const response = await api(id ? `/api/bibliography/${id}` : '/api/bibliography', {method: id ? 'PUT' : 'POST', formData: data});
        if (!response.success || !response.item) throw new Error(response.error || 'Запись не сохранена');
        if (id) items = items.map(item => String(item.id) === id ? response.item : item);
        else items.push(response.item);
        resetForm();
        renderRows();
        status(id ? 'Изменения сохранены.' : 'Источник добавлен.', 'success');
        $('newItemBtn').focus();
    } catch (error) { status(`Не удалось сохранить: ${error.message}. Введённые данные сохранены в карточке.`, 'error'); }
    finally { setBusy(false); }
});
$('newItemBtn').addEventListener('click', () => openEditor());
$('cancelEdit').addEventListener('click', () => {
    if (busy || !canDiscard()) return;
    resetForm();
    $('newItemBtn').focus();
});
$('bibBody').addEventListener('click', async event => {
    const button = event.target.closest('button[data-act]');
    if (!button || busy) return;
    const item = items.find(item => String(item.id) === button.dataset.id);
    if (!item) return;
    if (button.dataset.act === 'edit') return openEditor(item);
    if (!confirm(`Удалить источник «${item.title || 'Без названия'}»? Файл документа не удаляется.`)) return;
    setBusy(true);
    try {
        const response = await api(`/api/bibliography/${item.id}`, {method: 'DELETE'});
        if (!response.success) throw new Error(response.error || 'Удаление не выполнено');
        items = items.filter(row => row.id !== item.id);
        if (String(item.id) === $('itemId').value) resetForm();
        renderRows();
        status('Запись удалена. Файл документа сохранён.', 'success');
    } catch (error) { status(`Не удалось удалить: ${error.message}`, 'error'); }
    finally { setBusy(false); }
});
$('importFile').addEventListener('change', updateImportSelection);
$('cancelImportBtn').addEventListener('click', () => { $('importFile').value = ''; updateImportSelection(); });
$('importForm').addEventListener('submit', async event => {
    event.preventDefault();
    const file = $('importFile').files[0];
    if (busy || !file) return;
    if (!/\.(txt|bib|json)$/i.test(file.name)) return status('Выберите список в формате TXT, BibTeX или JSON.', 'error');
    const data = new FormData(); data.set('file', file);
    setBusy(true);
    status(`Добавляем записи из ${file.name}…`);
    try {
        const response = await api('/api/bibliography/import', {method: 'POST', formData: data});
        if (!response.success) throw new Error(response.error || 'Импорт не выполнен');
        $('importFile').value = '';
        try {
            await refresh();
            status(`Добавлено записей: ${response.count}. Прежние записи сохранены.`, 'success');
        } catch (error) {
            status(`Добавлено записей: ${response.count}, но список не обновлён: ${error.message}. Нажмите «Обновить список». Повторный импорт не требуется.`, 'error');
        }
    } catch (error) { status(`Не удалось импортировать: ${error.message}. Выбранный файл сохранён для повтора.`, 'error'); }
    finally { setBusy(false); }
});
$('refreshLibraryBtn').addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    try { await refresh(); status('Список обновлён. Правки открытой карточки сохранены в форме.', 'success'); }
    catch (error) { status(`Не удалось обновить: ${error.message}. Показан прежний список.`, 'error'); }
    finally { setBusy(false); }
});
$('bibSearch').addEventListener('input', renderRows);
window.addEventListener('beforeunload', event => {
    if (dirty() || busy) { event.preventDefault(); event.returnValue = ''; }
});
resetForm();
renderRows();
updateImportSelection();
