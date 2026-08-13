"use strict";

const $ = (id) => document.getElementById(id);

function collectForm() {
    const fd = new FormData();
    fd.set('authors', $('authors').value);
    fd.set('title', $('title').value);
    fd.set('doc_type', $('doc_type').value);
    fd.set('year', $('year').value);
    fd.set('journal', $('journal').value);
    fd.set('publisher', $('publisher').value);
    fd.set('city', $('city').value);
    fd.set('pages', $('pages').value);
    fd.set('isbn', $('isbn').value);
    fd.set('doi', $('doi').value);
    fd.set('source', $('source').value);
    return fd;
}

function fillForm(item) {
    $('itemId').value = item.id;
    $('authors').value = (item.authors || []).join('; ');
    $('title').value = item.title || '';
    $('doc_type').value = item.doc_type || 'article';
    $('year').value = item.year || '';
    $('journal').value = item.journal || '';
    $('publisher').value = item.publisher || '';
    $('city').value = item.city || '';
    $('pages').value = item.pages || '';
    $('isbn').value = item.isbn || '';
    $('doi').value = item.doi || '';
    $('source').value = item.source || '';
    $('bibEditor').open = true;
    $('cancelEdit').hidden = false;
    $('saveBtn').textContent = 'Обновить запись';
    $('bibEditor').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function resetForm() {
    $('itemId').value = '';
    $('bibForm').reset();
    $('cancelEdit').hidden = true;
    $('saveBtn').textContent = 'Сохранить запись';
    $('bibEditor').open = false;
}

function renderRows(items) {
    const body = $('bibBody');
    body.innerHTML = '';
    const q = ($('bibSearch').value || '').toLowerCase();
    let shown = 0;
    for (const item of items) {
        const hay = ((item.authors || []).join(' ') + ' ' + (item.title || '')).toLowerCase();
        if (q && !hay.includes(q)) continue;
        shown++;
        const tr = document.createElement('tr');
        tr.dataset.id = item.id;
        const title = esc(item.title || 'Без названия');
        tr.innerHTML =
            `<td><strong>${title}</strong><small>${esc((item.authors || []).join('; '))}</small></td>` +
            `<td>${esc(item.doc_type)}</td>` +
            `<td>${esc(item.year)}</td>` +
            `<td class="row-actions">` +
            `<button class="icon-button" data-act="edit" data-id="${esc(item.id)}" title="Редактировать" aria-label="Редактировать ${title}">✎</button>` +
            `<button class="icon-button danger-action" data-act="delete" data-id="${esc(item.id)}" title="Удалить" aria-label="Удалить ${title}">×</button>` +
            `</td>`;
        body.appendChild(tr);
    }
    $('bibCount').textContent = items.length;
    $('bibEmpty').hidden = shown !== 0;
}

// Загрузка списка с сервера (вместо location.reload)
async function refresh() {
    try {
        const items = await api('/api/bibliography');
        renderRows(items);
    } catch (_) { /* toast уже показан */ }
}

$('bibForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = $('itemId').value;
    const fd = collectForm();
    const btn = $('saveBtn');
    setLoading(btn, true);
    try {
        if (id) {
            await api(`/api/bibliography/${id}`, { method: 'PUT', formData: fd });
            toast('Запись обновлена', 'success');
        } else {
            await api('/api/bibliography', { method: 'POST', formData: fd });
            toast('Запись добавлена', 'success');
        }
        resetForm();
        await refresh();
    } catch (_) { /* toast уже показан */ }
    finally { setLoading(btn, false); }
});

$('newItemBtn').addEventListener('click', () => {
    resetForm();
    $('bibEditor').open = true;
    $('authors').focus();
});
$('cancelEdit').addEventListener('click', resetForm);

$('bibBody').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = Number(btn.dataset.id);
    const act = btn.dataset.act;
    if (act === 'edit') {
        const items = await api('/api/bibliography');
        const item = items.find((i) => i.id === id);
        if (item) fillForm(item);
    } else if (act === 'delete') {
        if (!confirm('Удалить запись?')) return;
        setLoading(btn, true);
        try {
            await api(`/api/bibliography/${id}`, { method: 'DELETE' });
            toast('Запись удалена', 'success');
            await refresh();
        } catch (_) { /* toast уже показан */ }
        finally { setLoading(btn, false); }
    }
});

$('importForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = $('importFile');
    if (!fileInput.files[0]) return;
    const fd = new FormData();
    fd.set('file', fileInput.files[0]);
    const btn = $('importBtn');
    setLoading(btn, true);
    try {
        const r = await api('/api/bibliography/import', { method: 'POST', formData: fd });
        toast(`Импортировано записей: ${r.count}`, 'success');
        fileInput.value = '';
        await refresh();
    } catch (_) { /* toast уже показан */ }
    finally { setLoading(btn, false); }
});

$('bibSearch').addEventListener('input', () => {
    api('/api/bibliography').then(renderRows).catch(() => {});
});
