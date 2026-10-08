"use strict";

const $ = (id) => document.getElementById(id);
let loaded = false;
let loading = false;
const types = {article: 'Статья', book: 'Книга', conference: 'Материалы конференции', dissertation: 'Диссертация', report: 'Отчёт', patent: 'Патент', standard: 'Стандарт', collection: 'Сборник'};

function setStatus(message, type = 'info') {
    $('status').hidden = !message;
    $('status').className = 'status-bar ' + type;
    $('status').textContent = message || '';
}

function renderStats(data) {
    $('stats').innerHTML = `<strong>${esc(String(data.total_bib))}</strong> записей в библиотеке`;
    const stats = [
        ['Входные файлы', data.total_files, 'в папке исходников'],
        ['Файлы результата', data.matched_files, 'в папке копий; наличие не подтверждает связь'],
    ];
    $('fileStats').innerHTML = stats.map(([label, value, note]) =>
        `<div class="metric-card"><span>${esc(label)}</span><strong>${esc(String(value))}</strong><small>${esc(note)}</small></div>`
    ).join('');
    const entries = Object.entries(data.doc_types || {});
    const max = Math.max(1, ...entries.map(([, value]) => value));
    $('docTypes').innerHTML = entries.length
        ? entries.map(([name, value]) => `<div class="type-row"><span>${esc(types[name] || name)}</span><div><i style="width:${Math.round(value / max * 100)}%"></i></div><strong>${esc(String(value))}</strong></div>`).join('')
        : '<p class="field-help">Библиотека пуста. <a href="/bibliography">Добавить источники</a></p>';
}

function renderMatching(report) {
    const element = $('lastMatching');
    if (!report) {
        element.innerHTML = '<p class="field-help">Сопоставление ещё не запускалось. <a href="/matching">Найти соответствия</a></p>';
        return;
    }
    const matched = Array.isArray(report.matched) ? report.matched : [];
    const unmatched = Array.isArray(report.unmatched) ? report.unmatched : [];
    const errors = Array.isArray(report.errors) ? report.errors : [];
    let html = `<p class="field-help">${report.dry_run ? 'Последний запуск — только проверка соответствий. Копии не создавались.' : 'Сохранённый отчёт последнего запуска. Изменения файлов и записей после него здесь не проверены.'}</p>`;
    html += `<div class="matching-kpis"><span><strong>${matched.length}</strong> соответствий</span><span><strong>${unmatched.length}</strong> без соответствия</span><span><strong>${errors.length}</strong> ошибок</span></div>`;
    if (errors.length) html += '<ul class="issue-list">' + errors.map(error =>
        `<li>${esc(error.original || error.file || '')}: ${esc(error.message || error.error || error.code || 'Ошибка обработки')}</li>`
    ).join('') + '</ul>';
    if (matched.length) {
        html += `<details class="workspace-disclosure"><summary>Соответствия (${matched.length})</summary><div class="table-scroll"><table><thead><tr><th>Исходник</th><th>Имя результата</th><th>Копирование</th></tr></thead><tbody>`;
        html += matched.map(row => `<tr><td>${esc(row.original || '')}</td><td>${esc(row.new || row.planned_name || '—')}</td><td>${esc(report.dry_run ? 'Только план' : row.copied === true ? 'Копия создана' : row.copied === false ? 'Копия не создана' : 'Нет сведений')}</td></tr>`).join('');
        html += '</tbody></table></div></details>';
    }
    if (unmatched.length) html += `<details class="workspace-disclosure"><summary>Без соответствия (${unmatched.length})</summary><ul>` + unmatched.map(row =>
        `<li>${esc(typeof row === 'string' ? row : row.original || row.file || row.name || 'Без имени')}</li>`
    ).join('') + '</ul></details>';
    element.innerHTML = html;
}

async function loadAll(notify = false) {
    if (loading) return;
    loading = true;
    window.setLoading($('refreshBtn'), true);
    setStatus('');
    try {
        const data = await api('/api/stats');
        renderStats(data);
        renderMatching(data.matching);
        loaded = true;
        if (notify) window.toast('Обзор библиотеки обновлён', 'success');
    } catch (error) {
        if (!loaded) {
            $('stats').innerHTML = '';
            $('fileStats').innerHTML = '';
            $('docTypes').textContent = 'Данные не загружены.';
            $('lastMatching').textContent = 'Отчёт не загружен.';
        }
        setStatus(`Не удалось обновить данные: ${error.message}. ${loaded ? 'Показаны предыдущие данные.' : 'Повторите обновление.'}`, 'error');
    } finally {
        loading = false;
        window.setLoading($('refreshBtn'), false);
    }
}

$('refreshBtn').addEventListener('click', () => loadAll(true));
loadAll();
