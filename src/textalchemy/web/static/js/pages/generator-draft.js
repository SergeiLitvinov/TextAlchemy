"use strict";

const PREFIX = 'textalchemy.generator-draft.v1.';
const LAST = 'textalchemy.generator-selected.v1';

export function createGeneratorDraft($) {
    let active = null, blocked = false, unsaved = false;
    const visited = new Map();
    const recoverable = new Set();
    const message = text => { $('draftStatus').textContent = text; };
    function read(key) {
        try { return sessionStorage.getItem(key); }
        catch (_) { message('Хранилище вкладки недоступно. Ввод не восстановится после перезагрузки.'); return null; }
    }
    function format() { return $('formatGroup').querySelector('.active').dataset.format; }
    function initial(names) {
        const saved = read(LAST);
        if (saved && !names.includes(saved)) message('Сохранённый шаблон недоступен. Его черновик не удалён.');
        return names.includes(saved) ? saved : names[0];
    }
    function begin(name, schema, supplied = null, restore = false) {
        active = {name, schema}; blocked = false; unsaved = false;
        $('restoreDraft').hidden = true;
        message('Для этого шаблона ещё нет сохранённого черновика.');
        try { sessionStorage.setItem(LAST, name); }
        catch (_) { message('Хранилище вкладки недоступно.'); }
        const raw = supplied ? JSON.stringify(supplied) : !restore && visited.has(name) ?
            JSON.stringify(visited.get(name)) : read(PREFIX + name);
        const firstVisit = !visited.has(name);
        if (firstVisit && !supplied && !restore) {
            $('output').value = 'output.docx';
            $('formatGroup').querySelectorAll('.format-option').forEach(button => button.classList.toggle('active', button.dataset.format === 'docx'));
        }
        if (firstVisit) visited.set(name, snapshot());
        if (!raw) return;
        if (firstVisit && !supplied && !restore) {
            recoverable.add(name);
            $('restoreDraft').hidden = false;
            message('Открыта новая форма. Предыдущий черновик можно восстановить явно, включая изображения.');
            return false;
        }
        try {
            const draft = JSON.parse(raw);
            if (draft.version !== 1 || draft.schema !== JSON.stringify(schema) || !Array.isArray(draft.values) ||
                draft.values.length !== schema.fields.length || !['docx', 'pdf', 'html'].includes(draft.format) ||
                typeof draft.output !== 'string') throw new Error('schema');
            // Validate the entire snapshot before applying any field.
            draft.values.forEach((value, index) => {
                const field = schema.fields[index];
                if (value.name !== field.name || typeof value.value !== (field.type === 'boolean' ? 'boolean' : 'string')) {
                    throw new Error('field');
                }
            });
            draft.values.forEach(value => {
                const input = $('field-' + value.name);
                if (input.type === 'checkbox') input.checked = value.value;
                else if (input.type === 'file') {
                    input.value = '';
                    input.parentElement.querySelector('[data-restored-image]')?.remove();
                    input.dataset.imageData = value.value;
                    if (value.value) {
                        const note = document.createElement('p'); note.className = 'field-help';
                        note.dataset.restoredImage = 'true';
                        note.textContent = 'Изображение восстановлено из черновика. Новый выбор заменит его.';
                        input.parentElement.append(note);
                    }
                } else input.value = value.value;
            });
            $('output').value = draft.output;
            $('formatGroup').querySelectorAll('.format-option').forEach(button => {
                button.classList.toggle('active', button.dataset.format === draft.format);
            });
            message('Черновик восстановлен в этой вкладке. Данные будут проверены перед генерацией.');
            if (restore || supplied) recoverable.delete(name);
            $('restoreDraft').hidden = !recoverable.has(name);
            return true;
        } catch (_) {
            blocked = true;
            message('Черновик не восстановлен: данные повреждены или схема шаблона изменилась. Он сохранён без изменений. Удалите его явно, чтобы начать новый.');
            return false;
        }
    }
    function snapshot() {
        if (!active) throw new Error('Дождитесь загрузки шаблона.');
        const values = active.schema.fields.map(field => {
            const input = $('field-' + field.name);
            return {name: field.name, value: input.type === 'checkbox' ? input.checked :
                input.type === 'file' ? (input.dataset.imageData || '') : input.value};
        });
        return {version: 1, schema: JSON.stringify(active.schema), values, output: $('output').value, format: format()};
    }
    function save() {
        if (!active) return;
        unsaved = true;
        if (blocked) return;
        try {
            sessionStorage.setItem(PREFIX + active.name, JSON.stringify(snapshot()));
            sessionStorage.setItem(LAST, active.name);
            $('restoreDraft').hidden = true;
            recoverable.delete(active.name);
            unsaved = false; message('Черновик сохранён в этой вкладке.');
        } catch (_) { message('Черновик не сохранён: хранилище недоступно или заполнено. Ввод остаётся на экране.'); }
    }
    function forget() {
        if (!active || !confirm('Удалить черновик этого шаблона в этой вкладке и сбросить поля?')) return false;
        try {
            sessionStorage.removeItem(PREFIX + active.name);
            visited.delete(active.name); recoverable.delete(active.name); active = null;
            $('output').value = 'output.docx';
            $('formatGroup').querySelectorAll('.format-option').forEach(button => {
                button.classList.toggle('active', button.dataset.format === 'docx');
            });
            blocked = false; unsaved = false; message('Черновик удалён.'); return true;
        } catch (_) { message('Не удалось удалить черновик.'); return false; }
    }
    window.addEventListener('beforeunload', event => {
        if (unsaved) { event.preventDefault(); event.returnValue = ''; }
    });
    return {initial, begin, save, forget, snapshot,
        restore() { return active && begin(active.name, active.schema, null, true); },
        pause() { if (active) visited.set(active.name, snapshot()); active = null; },
        pendingImage() { unsaved = true; message('Изображение загружается; черновик ещё не обновлён.'); },
        imageError() { unsaved = true; message('Не удалось прочитать изображение. Выберите его заново.'); },
        canSwitch() { return !unsaved || confirm('Последние изменения не сохранены. Сменить шаблон без их сохранения?'); }};
}
