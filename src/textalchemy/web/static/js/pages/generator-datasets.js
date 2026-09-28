"use strict";

export function createGeneratorDatasets($, snapshot, apply) {
    let template = null, selected = null, epoch = 0, busy = false;
    const message = text => { $('datasetStatus').textContent = text; };
    function controls() {
        $('datasetCreate').disabled = busy || !template;
        $('datasetUpdate').disabled = busy || !selected || selected.id !== $('datasetList').value;
        $('datasetLoad').disabled = busy || !$('datasetList').value;
        $('datasetList').disabled = busy;
        $('datasetName').disabled = busy;
    }
    async function refresh(token, choose = '') {
        const list = await window.api('/api/generate/datasets?template=' + encodeURIComponent(template));
        if (token !== epoch) return;
        $('datasetList').replaceChildren(new Option('— выберите набор —', ''),
            ...list.map(item => new Option(item.name, item.id)));
        $('datasetList').value = choose;
    }
    async function run(action) {
        if (busy || !template) return;
        const token = epoch; busy = true; controls();
        try { await action(token); }
        catch (error) { if (token === epoch) message(error.message || 'Не удалось сохранить набор.'); }
        finally { if (token === epoch) { busy = false; controls(); } }
    }
    async function save(update, token) {
        const payload = {template, name: $('datasetName').value, snapshot: snapshot()};
        if (update) payload.revision = selected.revision;
        const saved = await window.api('/api/generate/datasets' + (update ? '/' + encodeURIComponent(selected.id) : ''),
            {method: update ? 'PUT' : 'POST', json: payload});
        if (token !== epoch) return;
        selected = saved;
        await refresh(token, saved.id);
        if (token === epoch) message(`Набор «${saved.name}» сохранён, версия ${saved.revision}. Последующие правки требуют обновления набора.`);
    }
    $('datasetCreate').onclick = () => run(token => save(false, token));
    $('datasetUpdate').onclick = () => run(token => save(true, token));
    $('datasetList').onchange = () => { selected = null; controls(); };
    $('datasetLoad').onclick = () => {
        if (!confirm('Заменить текущие поля, формат и имя файла данными выбранного набора?')) return;
        run(async token => {
            const before = JSON.stringify(snapshot());
            const data = await window.api('/api/generate/datasets/' + encodeURIComponent($('datasetList').value));
            if (token !== epoch) return;
            if (before !== JSON.stringify(snapshot())) throw new Error('Форма изменилась во время загрузки. Повторите загрузку набора.');
            if (data.template !== template || !apply(data.snapshot)) throw new Error('Набор несовместим с текущей схемой.');
            selected = data; $('datasetName').value = data.name;
            message(`Загружен набор «${data.name}», версия ${data.revision}. Проверьте данные перед генерацией.`);
        });
    };
    return {async bind(name) {
        template = name; selected = null; busy = false; const token = ++epoch;
        $('datasetList').replaceChildren(new Option('— выберите набор —', '')); $('datasetName').value = '';
        message(name ? 'Загружаем наборы этого шаблона…' : 'Выберите шаблон.'); controls();
        if (name) await run(async () => { await refresh(token); if (token === epoch) message('Выберите набор или сохраните новый.'); });
    }};
}
