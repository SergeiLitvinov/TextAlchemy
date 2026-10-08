"use strict";

const $ = (id) => document.getElementById(id);

function renderResults(data, isPreview) {
    const body = $('resultsBody');
    body.innerHTML = '';
    const rows = isPreview ? data.preview : (data.matched.concat(
        data.unmatched.map((u) => ({ original: u.file, new: '—', match: false, score: 0 }))
    ));
    for (const item of rows) {
        const tr = document.createElement('tr');
        const source = item.source;
        const description = source ? `<strong>${esc(source.title)}</strong><small>${esc((source.authors || []).join(', '))}${source.year ? ' · ' + esc(source.year) : ''}</small>`
            : item.match ? 'Источник найден' : 'Соответствие не найдено';
        tr.innerHTML =
            `<td>${esc(item.original)}</td>` +
            `<td class="matching-source">${description}</td>` +
            `<td>${esc(item.new || (data.dry_run ? item.planned_name : 'Копия не создана'))}</td>` +
            `<td>${esc(item.score)}</td>`;
        body.appendChild(tr);
    }
    const matched = isPreview ? data.matched : data.matched.length;
    const unmatched = isPreview ? (data.total - data.matched) : data.unmatched.length;
    $('resultsSummary').textContent =
        `Всего: ${data.total}, совпадений: ${matched}, без совпадений: ${unmatched}` +
        (data.errors && data.errors.length ? `, ошибок: ${data.errors.length}` : '');
    $('resultsCard').hidden = false;
    $('matchingFinish').hidden = false;
    window._lastReport = data;
}

function setStatus(msg, type) {
    const el = $('status');
    el.hidden = !msg;
    if (!msg) return;
    el.className = 'status-bar ' + (type || 'info');
    el.textContent = msg;
}

$('matchForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData();
    fd.set('source_dir', $('source_dir').value);
    fd.set('threshold', $('threshold').value);
    fd.set('bibliography_file', $('bibliography_file').value);
    const btn = $('previewBtn');
    setLoading(btn, true);
    setStatus('Анализ файлов…', 'info');
    try {
        const data = await api('/api/preview/rename', { method: 'POST', formData: fd });
        renderResults(data, true);
        setStatus('Поиск завершён. Проверьте найденные источники.', 'success');
    } catch (_) { setStatus('', null); }
    finally { setLoading(btn, false); }
});

$('runBtn').addEventListener('click', async () => {
    const fd = new FormData();
    fd.set('source_dir', $('source_dir').value);
    fd.set('output_dir', $('output_dir').value);
    fd.set('threshold', $('threshold').value);
    fd.set('bibliography_file', $('bibliography_file').value);
    fd.set('dry_run', $('dryRun').checked ? 'true' : 'false');
    const btn = $('runBtn');
    setLoading(btn, true);
    setStatus('Сопоставление выполняется…', 'info');
    try {
        const data = await api('/api/match/run', { method: 'POST', formData: fd });
        renderResults(data, false);
        const verb = data.dry_run ? 'Предпросмотр завершён' : 'Копирование завершено';
        const errors = data.errors ? data.errors.length : 0;
        setStatus(`${verb}: совпало ${data.matched.length}, без совпадений ${data.unmatched.length}` +
            (errors ? `, копия не создана для ${errors} файлов.` : '.'), errors ? 'error' : 'success');
        toast(errors ? 'Проверьте ошибки копирования' : 'Сопоставление завершено', errors ? 'error' : 'success');
    } catch (_) { setStatus('', null); }
    finally { setLoading(btn, false); }
});

$('downloadBtn').addEventListener('click', () => {
    if (!window._lastReport) return;
    const blob = new Blob([JSON.stringify(window._lastReport, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'matching_report.json';
    a.click();
    URL.revokeObjectURL(a.href);
});

function updateRunAction() {
    $('runBtn').textContent = $('dryRun').checked ? 'Составить отчёт' : 'Копировать с новыми именами';
    $('copyDestination').hidden = $('dryRun').checked;
}
$('dryRun').addEventListener('change', updateRunAction);
updateRunAction();
for (const id of ['source_dir', 'threshold', 'bibliography_file']) {
    $(id).addEventListener('input', () => {
        $('resultsCard').hidden = true; $('matchingFinish').hidden = true;
        $('directorySnapshot').hidden = true; window._lastReport = null;
        setStatus('Параметры изменены. Повторите поиск, чтобы проверить новые предложения.');
    });
}
