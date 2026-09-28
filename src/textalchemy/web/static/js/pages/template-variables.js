"use strict";

export function createTemplateVariables($, useCopy) {
    let name = null, inspection = null, epoch = 0, busy = false;
    const status = text => { $('variableStatus').textContent = text; };
    function controls() {
        $('variableInspect').disabled = busy || !name;
        $('variableSave').disabled = busy || !inspection || !$('variableSelect').value;
        $('variableSelect').disabled = busy;
        $('variableName').disabled = busy;
    }
    function context() {
        const item = inspection?.variables.find(item => item.name === $('variableSelect').value);
        $('variableContext').textContent = item ? item.contexts.join('\n') : '';
        controls();
    }
    async function run(action) {
        if (busy || !name) return;
        const token = epoch; busy = true; controls();
        try { await action(token); }
        catch (error) { if (token === epoch) status(error.message); }
        finally { if (token === epoch) { busy = false; controls(); } }
    }
    $('variableInspect').onclick = () => run(async token => {
        const result = await window.api('/api/generate/templates/' + encodeURIComponent(name) + '/variables');
        if (token !== epoch) return;
        inspection = result;
        $('variableSelect').replaceChildren(...result.variables.map(item => new Option(item.name, item.name)));
        context();
        status(result.variables.length ? 'Выберите переменную и задайте новое имя.' : 'Простых переменных нет.');
    });
    $('variableSelect').onchange = context;
    $('variableSave').onclick = () => run(async token => {
        const result = await window.api('/api/generate/templates/' + encodeURIComponent(name) + '/variables', {
            method: 'POST', json: {old: $('variableSelect').value, new: $('variableName').value.trim(), revision: inspection.revision}
        });
        if (token !== epoch) return;
        await useCopy(result.name);
        status('Копия сохранена и доступна в списке шаблонов. Заполните её поля и создайте документ.');
    });
    return {bind(template) {
        name = template; inspection = null; epoch++; busy = false;
        $('variableSelect').replaceChildren(); $('variableName').value = ''; $('variableContext').textContent = '';
        status('Загрузите переменные выбранного шаблона.'); controls();
    }};
}
