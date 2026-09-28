"use strict";
export function createRichEditor($, useCopy) {
    let name = null, inspection = null, busy = false, epoch = 0;
    const status = message => { $('richStatus').textContent = message; };
    function controls() {
        $('richInspect').disabled = busy || !name; $('richSave').disabled = busy || !inspection;
    }
    async function run(action) {
        if (busy || !name) return;
        busy = true; controls(); const token = epoch;
        try { await action(token); } catch (error) { if (token === epoch) status(error.message); }
        finally { busy = false; controls(); }
    }
    $('richInspect').onclick = () => run(async token => {
        const data = await window.api('/api/generate/templates/' + encodeURIComponent(name) + '/source');
        if (token !== epoch) return;
        inspection = data;
        $('richBlock').replaceChildren(...data.blocks.filter(b => b.id.startsWith('word/document.xml:'))
            .map(b => new Option(b.text.slice(0, 120), b.id)));
        status('Выбранный абзац будет заменён содержимым; метка сохраняет его текст.');
    });
    $('richSave').onclick = () => run(async () => {
        const data = await window.api('/api/generate/templates/' + encodeURIComponent(name) + '/rich', {method: 'POST', json: {
            block: $('richBlock').value, kind: $('richKind').value, field: $('richField').value, expected: inspection.revision,
        }});
        await useCopy(data.name); status('Копия сохранена. Заполните данные и проверьте результат.');
    });
    return {bind(value) { name = value; inspection = null; epoch++; $('richBlock').replaceChildren(); controls(); }};
}
