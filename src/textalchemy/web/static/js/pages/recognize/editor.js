"use strict";

import {createParagraphOrder} from './order.js';

export function createOcrEditor($, setStatus) {
    let draft = null;
    let dirty = false;
    let busy = false;
    const result = $('result');
    const order = createParagraphOrder($, () => { dirty = true; controls(); });

    function controls() {
        result.readOnly = busy;
        order.update(Boolean(draft) && !busy);
        $('saveTextBtn').disabled = busy || !draft || !dirty;
        $('exportTextBtn').disabled = busy || !draft;
        $('ocrExportFormat').disabled = busy || !draft;
        $('reloadTextBtn').disabled = busy || !draft;
        $('copyBtn').disabled = busy || !draft;
        $('editStatus').textContent = !draft ? '' : dirty ? 'Есть несохранённые правки' : 'Текст сохранён';
    }

    function accept(data) {
        draft = data;
        result.value = data.text;
        result.hidden = false;
        $('resultEmpty').hidden = true;
        dirty = false;
        const url = new URL(window.location.href);
        url.searchParams.set('draft', draft.draft_id);
        history.replaceState(null, '', url);
        controls();
    }

    function setBusy(value) { busy = value; controls(); }

    function canReplace() {
        return !busy && (!dirty || window.confirm('Есть несохранённые правки. Продолжить без их сохранения?'));
    }

    async function restore() {
        const id = draft?.draft_id || new URL(window.location.href).searchParams.get('draft');
        if (!id || !canReplace()) return;
        setBusy(true);
        try {
            accept(await window.api('/api/recognize/drafts/' + encodeURIComponent(id)));
            setStatus('Сохранённый текст восстановлен. Можно продолжить правку.', 'info');
        } catch (error) { setStatus(error.message || 'Не удалось загрузить сохранённый текст.', 'error'); }
        finally { setBusy(false); }
    }

    async function save() {
        const data = await window.api('/api/recognize/drafts/' + encodeURIComponent(draft.draft_id), {
            method: 'PUT', json: {text: result.value, revision: draft.revision},
        });
        accept(data);
    }

    async function saveOrExport(download) {
        if (!draft || busy) return;
        const format = $('ocrExportFormat').value;
        setBusy(true);
        try {
            if (dirty) await save();
            if (download) {
                const url = `/api/recognize/drafts/${encodeURIComponent(draft.draft_id)}/export` +
                    `?format=${encodeURIComponent(format)}&revision=${draft.revision}`;
                const response = await fetch(url, {cache: 'no-store'});
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Не удалось скачать текст. Правки сохранены; повторите скачивание.');
                }
                const blobUrl = URL.createObjectURL(await response.blob());
                const anchor = document.createElement('a');
                anchor.href = blobUrl;
                anchor.download = format === 'model' ? 'corrected.model.json' : `corrected.${format}`;
                anchor.click();
                setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
            }
            setStatus(download ? 'Исправленный текст сохранён и отправлен на скачивание.' : 'Правки сохранены.', 'success');
        } catch (error) { setStatus(error.message || 'Не удалось сохранить текст. Правки остаются в поле.', 'error'); }
        finally { setBusy(false); }
    }

    result.addEventListener('input', () => { dirty = true; controls(); });
    $('saveTextBtn').addEventListener('click', () => saveOrExport(false));
    $('exportTextBtn').addEventListener('click', () => saveOrExport(true));
    $('reloadTextBtn').addEventListener('click', restore);
    window.addEventListener('beforeunload', (event) => {
        if (dirty) { event.preventDefault(); event.returnValue = ''; }
    });
    controls();
    restore();
    return {accept, canReplace, setBusy};
}
