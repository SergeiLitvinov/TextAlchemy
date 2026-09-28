"use strict";

export function createTemplateLoops(lookup, useCopy, table = false) {
    const $ = id => lookup(table ? id.replace(/^loop/, 'rowLoop') : id);
    const endpoint = table ? '/table-loops' : '/loops';
    const noun = table ? 'строку' : 'абзац';
    let name = null, inspection = null, epoch = 0, busy = false;
    const status = text => { $('loopStatus').textContent = text; };
    function controls() {
        $('loopInspect').disabled = busy || !name;
        $('loopSave').disabled = busy || !inspection || !$('loopVariable').value;
        for (const id of ['loopBlock', 'loopField', 'loopVariable']) $(id).disabled = busy;
    }
    function selection() {
        const block = inspection?.blocks.find(item => String(item.id) === $('loopBlock').value);
        $('loopContext').textContent = block?.text || '';
        $('loopField').value = block?.field || 'items';
        $('loopVariable').replaceChildren(...(block?.variables || []).map(value =>
            new Option(value === '__ta_item' ? 'Текущее значение списка' : value, value)));
        controls();
    }
    async function run(action) {
        if (busy || !name) return;
        const token = epoch; busy = true; controls();
        try { await action(token); }
        catch (error) { if (token === epoch) status(error.message); }
        finally { if (token === epoch) { busy = false; controls(); } }
    }
    $('loopInspect').onclick = () => run(async token => {
        const result = await window.api('/api/generate/templates/' + encodeURIComponent(name) + endpoint);
        if (token !== epoch) return;
        inspection = result;
        $('loopBlock').replaceChildren(...result.blocks.map(item =>
            new Option(item.text.slice(0, 80) + (item.field ? ' — повторяется' : ''), item.id)));
        selection(); status(result.blocks.length ? `Выберите ${noun}, переменную и поле-список.` : 'Подходящих элементов нет.');
    });
    $('loopBlock').onchange = selection;
    $('loopSave').onclick = () => run(async token => {
        const result = await window.api('/api/generate/templates/' + encodeURIComponent(name) + endpoint, {
            method: 'POST', json: {block: table ? $('loopBlock').value : Number($('loopBlock').value), field: $('loopField').value.trim(),
                variable: $('loopVariable').value, revision: inspection.revision}
        });
        if (token !== epoch) return;
        await useCopy(result.name);
        status('Копия с циклом сохранена. Заполните список в данных документа и создайте результат.');
    });
    return {bind(template) {
        name = template; inspection = null; epoch++; busy = false;
        $('loopBlock').replaceChildren(); $('loopVariable').replaceChildren(); $('loopContext').textContent = '';
        $('loopField').value = 'items'; status(table ? 'Загрузите строки выбранного шаблона.' : 'Загрузите абзацы выбранного шаблона.'); controls();
    }};
}
