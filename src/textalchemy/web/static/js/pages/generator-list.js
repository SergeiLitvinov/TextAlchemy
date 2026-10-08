"use strict";

// The existing textarea stays the source for validation, drafts and named datasets.
export function createListEditor(input, label) {
    const root = document.createElement('div'); root.className = 'list-editor';
    root.setAttribute('role', 'group'); root.setAttribute('aria-label', label);
    const modes = document.createElement('div'); modes.className = 'workspace-modes segmented';
    const rows = document.createElement('div'); rows.className = 'list-rows';
    const note = document.createElement('p'); note.className = 'field-help'; note.setAttribute('role', 'status');
    let values = [];
    function button(text, action, aria = text) {
        const element = document.createElement('button'); element.type = 'button';
        element.className = 'btn-secondary'; element.textContent = text;
        element.setAttribute('aria-label', aria); element.onclick = action; return element;
    }
    const simple = button('По строкам', () => refresh(true));
    const json = button('JSON', () => mode(false));
    simple.className = json.className = 'seg-btn';
    const add = button('Добавить строку', () => { values.push(''); commit(); render(values.length - 1); });
    modes.append(simple, json); root.append(modes, note, rows, add);
    input.before(root);

    function mode(visual) {
        rows.hidden = add.hidden = !visual; input.hidden = visual;
        for (const [control, active] of [[simple, visual], [json, !visual]]) {
            control.classList.toggle('active', active);
            control.setAttribute('aria-pressed', String(active));
        }
        if (!visual) note.textContent = 'Текстовый режим сохраняет любые значения и их типы. Для простого списка текста можно вернуться к строкам.';
    }
    function commit() {
        input.value = JSON.stringify(values);
        input.dispatchEvent(new Event('input', {bubbles: true}));
    }
    function render(focus = null) {
        rows.replaceChildren();
        note.textContent = values.length ? `Строк: ${values.length}. Порядок и повторяющиеся значения сохраняются.` : 'Список пуст. Добавьте первую строку.';
        add.disabled = values.length >= 200;
        if (add.disabled) note.textContent += ' Для более длинного списка используйте JSON.';
        values.forEach((value, index) => {
            const row = document.createElement('div'); row.className = 'list-row';
            const text = document.createElement('textarea'); text.rows = 2; text.value = value;
            text.setAttribute('aria-label', `${label}: строка ${index + 1}`);
            text.oninput = event => { event.stopPropagation(); values[index] = text.value; commit(); };
            const actions = document.createElement('div'); actions.className = 'list-row-actions';
            const move = delta => {
                const target = index + delta;
                [values[index], values[target]] = [values[target], values[index]];
                commit(); render(target);
            };
            const up = button('Выше', () => move(-1), `Строка ${index + 1}: выше`); up.disabled = index === 0;
            const down = button('Ниже', () => move(1), `Строка ${index + 1}: ниже`); down.disabled = index === values.length - 1;
            const remove = button('Удалить', () => {
                values.splice(index, 1); commit(); render(Math.min(index, values.length - 1));
                if (!values.length) add.focus();
            }, `Удалить строку ${index + 1}`);
            actions.append(up, down, remove); row.append(text, actions); rows.append(row);
        });
        if (focus !== null) rows.children[focus]?.querySelector('textarea').focus();
    }
    function refresh(requested = false) {
        try {
            const parsed = input.value.trim() ? JSON.parse(input.value) : [];
            if (!Array.isArray(parsed) || parsed.some(value => typeof value !== 'string')) {
                throw new Error('Этот список содержит числа, объекты или другие нетекстовые значения. Изменяйте его в JSON: типы данных сохраняются.');
            }
            if (parsed.length > 200) throw new Error('Списки длиннее 200 строк редактируются в JSON. Все значения сохранены.');
            values = parsed; mode(true); render();
            if (requested) (rows.querySelector('textarea') || add).focus();
        } catch (error) {
            mode(false);
            note.textContent = error instanceof SyntaxError ? 'JSON пока не завершён или содержит ошибку. Исправьте его перед переходом к строкам; введённый текст сохранён.' : error.message;
        }
    }
    refresh();
    return {refresh};
}
