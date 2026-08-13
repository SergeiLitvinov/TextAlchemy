"use strict";

const $ = (id) => document.getElementById(id);
function setStatus(msg, type) {
    const el = $('status');
    el.hidden = !msg;
    if (!msg) return;
    el.className = 'status-bar ' + (type || 'info');
    el.textContent = msg;
}

function renderStats(d) {
    const stats = [
        ['Источники', d.total_bib, 'записей в библиотеке'],
        ['Документы', d.total_files, 'файлов обнаружено'],
        ['Связано', d.matched_files, 'записей с документами'],
        ['Готовность', d.progress + '%', d.unmatched + ' требуют внимания'],
    ];
    $('stats').innerHTML = stats.map(([label, value, note]) =>
        `<div class="metric-card"><span>${esc(label)}</span><strong>${esc(String(value))}</strong><small>${esc(note)}</small></div>`
    ).join('');
    const dt = Object.entries(d.doc_types || {});
    const max = Math.max(1, ...dt.map(([, value]) => value));
    $('docTypes').innerHTML = dt.length
        ? dt.map(([name, value]) => `<div class="type-row"><span>${esc(name)}</span><div><i style="width:${Math.round(value / max * 100)}%"></i></div><strong>${esc(String(value))}</strong></div>`).join('')
        : '<div class="empty-state"><span aria-hidden="true">▤</span><p><strong>Пока нет данных</strong><small>Добавьте источники, чтобы увидеть распределение.</small></p></div>';
}

function renderMatching(r) {
    const el = $('lastMatching');
    if (!r) {
        el.innerHTML = '<div class="empty-state"><span aria-hidden="true">⌁</span><p><strong>Проверка ещё не запускалась</strong><small>Свяжите записи с файлами, чтобы увидеть качество коллекции.</small></p></div>';
        return;
    }
    const matched = Array.isArray(r.matched) ? r.matched : [];
    const unmatched = Array.isArray(r.unmatched) ? r.unmatched : [];
    const errors = Array.isArray(r.errors) ? r.errors : [];
    let html = `<div class="matching-kpis"><span><strong>${matched.length}</strong> связано</span><span><strong>${unmatched.length}</strong> без связи</span><span><strong>${errors.length}</strong> ошибок</span></div>`;
    if (matched.length) {
        html += '<table><thead><tr><th>Оригинал</th><th>Новое имя</th><th>Оценка</th></tr></thead><tbody>';
        html += matched.map((m) => `<tr><td>${esc(m.original || '')}</td><td>${esc(m.new || '')}</td><td>${esc(String(m.score ?? ''))}</td></tr>`).join('');
        html += '</tbody></table>';
    }
    el.innerHTML = html;
}

async function loadAll() {
    try {
        const d = await api('/api/stats');
        renderStats(d);
        renderMatching(d.matching);
    } catch (_) { /* toast уже показан */ }
}
loadAll();
$('refreshBtn').addEventListener('click', () => { setStatus('Обновление…', 'info'); loadAll(); setTimeout(() => setStatus('', null), 1200); });
