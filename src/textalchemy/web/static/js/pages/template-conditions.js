"use strict";

export function createTemplateConditions($, useCopy) {
    let name = null, inspection = null, epoch = 0, busy = false;
    const status = text => { $('conditionStatus').textContent = text; };
    function controls() {
        $('conditionInspect').disabled = busy || !name;
        $('conditionSave').disabled = busy || !inspection || !$('conditionBlock').value;
        for (const id of ['conditionBlock', 'conditionField', 'conditionNegate']) $(id).disabled = busy;
    }
    function selection() {
        const block = inspection?.blocks.find(item => String(item.id) === $('conditionBlock').value);
        $('conditionContext').textContent = block?.text || '';
        $('conditionField').value = block?.field || 'show_section';
        $('conditionNegate').checked = block?.negate || false;
        controls();
    }
    async function run(action) {
        if (busy || !name) return;
        const token = epoch; busy = true; controls();
        try { await action(token); }
        catch (error) { if (token === epoch) status(error.message); }
        finally { if (token === epoch) { busy = false; controls(); } }
    }
    $('conditionInspect').onclick = () => run(async token => {
        const result = await window.api('/api/generate/templates/' + encodeURIComponent(name) + '/conditions');
        if (token !== epoch) return;
        inspection = result;
        $('conditionBlock').replaceChildren(...result.blocks.map(item =>
            new Option(item.text.slice(0, 80) + (item.field ? ' — с условием' : ''), item.id)));
        selection(); status(result.blocks.length ? 'Выберите абзац и настройте условие.' : 'Доступных абзацев нет.');
    });
    $('conditionBlock').onchange = selection;
    $('conditionSave').onclick = () => run(async token => {
        const result = await window.api('/api/generate/templates/' + encodeURIComponent(name) + '/conditions', {
            method: 'POST', json: {block: Number($('conditionBlock').value), field: $('conditionField').value.trim(),
                negate: $('conditionNegate').checked, revision: inspection.revision}
        });
        if (token !== epoch) return;
        await useCopy(result.name);
        status('Копия с условием сохранена. Заполните поля и проверьте документ с включённым и выключенным флажком.');
    });
    return {bind(template) {
        name = template; inspection = null; epoch++; busy = false;
        $('conditionBlock').replaceChildren(); $('conditionContext').textContent = '';
        $('conditionField').value = 'show_section'; $('conditionNegate').checked = false;
        status('Загрузите абзацы выбранного шаблона.'); controls();
    }};
}
