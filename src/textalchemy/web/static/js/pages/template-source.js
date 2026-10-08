"use strict";
export function createTemplateSource($, useCopy, edit) {
    let name = '', inspection = null, epoch = 0, busy = false;
    const status = text => { $('sourceStatus').textContent = text; };
    const url = () => '/api/generate/templates/' + encodeURIComponent(name) + '/source';
    function controls() {
        $('sourceInspect').disabled = busy || !name;
        $('sourceSearch').disabled = busy || !name;
        $('sourceSave').disabled = busy || !inspection || !$('sourceMatches').querySelector('input:checked');
    }
    async function run(action) {
        if (busy) return;
        busy = true; controls(); const token = epoch;
        try { await action(token); }
        catch (error) { if (token === epoch) status(error.message); }
        finally { busy = false; controls(); }
    }
    $('importTemplate').onclick = () => run(async () => {
        const file = $('sourceUpload').files[0];
        if (!file) { status('Сначала выберите DOCX.'); return; }
        const form = new FormData(); form.set('file', file);
        if ($('sourceSchema').value.trim()) form.set('schema', $('sourceSchema').value);
        const data = await window.api('/api/generate/import', {method: 'POST', formData: form});
        await useCopy(data.name); edit();
        $('sourceEditor').open = true;
        status('Образец сохранён отдельной копией. Покажите текст и выберите заменяемое значение.');
    });
    $('sourceInspect').onclick = () => run(async token => {
        const data = await window.api(url()); if (token !== epoch) return;
        $('sourceFields').hidden = false;
        $('sourceBlocks').replaceChildren(...data.blocks.map(block => new Option(`${block.location}: ${block.text.slice(0, 100)}`, block.id)));
        $('sourceBlocks').onchange = () => {
            const block = data.blocks.find(item => item.id === $('sourceBlocks').value);
            $('sourceQuery').value = block?.text || ''; $('sourceContext').textContent = block?.text || '';
            inspection = null; $('sourceMatches').replaceChildren(); controls();
        };
        $('sourceBlocks').onchange();
        $('sourceBlocks').focus();
        $('sourceSuggestions').replaceChildren(...data.suggestions.map(text => {
            const button = document.createElement('button'); button.type = 'button'; button.className = 'btn-secondary';
            button.textContent = text; button.onclick = () => { $('sourceQuery').value = text; $('sourceSearch').click(); };
            return button;
        }));
        status('Выберите абзац, оставьте в поле только изменяемое значение и найдите его вхождения.');
    });
    $('sourceSearch').onclick = () => run(async token => {
        const query = $('sourceQuery').value; if (!query.trim()) { status('Введите текст для замены.'); return; }
        const data = await window.api(url() + '?query=' + encodeURIComponent(query)); if (token !== epoch) return;
        inspection = {...data, query};
        $('sourceMatches').replaceChildren(...data.occurrences.map((item, index) => {
            const label = document.createElement('label'); label.className = 'source-occurrence';
            const input = document.createElement('input'); input.type = 'checkbox'; input.value = index;
            input.setAttribute('aria-label', `Вхождение ${index + 1}: ${item.location}`); input.onchange = controls;
            const text = document.createElement('span'), mark = document.createElement('mark'); mark.textContent = query;
            text.append(`${item.location}: `, item.text.slice(0, item.start), mark, item.text.slice(item.end));
            label.append(input, text); return label;
        }));
        status(data.occurrences.length ? `Найдено вхождений: ${data.occurrences.length}. Отметьте только связанные с одним значением.` : 'Совпадений нет. Проверьте точный текст.');
    });
    $('sourceQuery').oninput = () => { inspection = null; $('sourceMatches').replaceChildren(); controls(); };
    $('sourceSave').onclick = () => run(async () => {
        const selected = Array.from($('sourceMatches').querySelectorAll('input:checked')).map(input => inspection.occurrences[Number(input.value)]);
        const data = await window.api(url(), {method: 'POST', json: {query: inspection.query,
            label: $('sourceLabel').value, selected, expected: inspection.revision}});
        await useCopy(data.name);
        status('Поле сохранено. Введите новое значение в данных документа.');
    });
    return {bind(template) {
        name = template; epoch++; inspection = null;
        $('sourceFields').hidden = true;
        $('sourceBlocks').replaceChildren(); $('sourceMatches').replaceChildren(); $('sourceSuggestions').replaceChildren();
        $('sourceContext').textContent = ''; $('sourceQuery').value = ''; $('sourceLabel').value = ''; controls();
    }};
}
