"use strict";

export function createGeneratedPreview($, getParams, renderErrors) {
    let version = 0, result = null, page = 1, busy = false, timer = null, active = false, editing = false;
    let mode = 'live', beforeEdit = 'live';
    const note = text => { $(mode === 'pages' ? 'filledPreviewStatus' : 'livePreviewStatus').textContent = text; };
    const policy = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; form-action 'none'";
    const draftStyle = '<style>html{background:#fff}.ta-section{width:100%!important;min-height:0!important;margin:0!important;padding:clamp(20px,6vw,48px)!important;box-shadow:none}table{max-width:100%}body{overflow-wrap:anywhere}</style>';

    function show() {
        $('filledPreview').hidden = mode !== 'pages';
        $('livePreview').hidden = mode === 'pages';
        $('previewNote').hidden = false;
        $('previewNote').textContent = mode === 'pages'
            ? 'Страницы созданного файла. Проверяйте окончательный вид перед использованием.'
            : mode === 'source' ? 'Исходный шаблон: поля ещё не заполнены.'
            : 'Быстрый просмотр содержимого. Оформление и разбиение на страницы проверяйте в «Страницах результата».';
        $('preview-title').textContent = mode === 'pages' ? 'Страницы результата' : mode === 'source' ? 'Исходный шаблон' : 'Черновой просмотр';
        for (const [id, value] of [['previewFilled', 'live'], ['previewAccurate', 'pages'], ['previewSource', 'source']]) {
            $(id).hidden = editing;
            $(id).setAttribute('aria-pressed', String(mode === value));
        }
    }
    function renderPages() {
        $('filledPageLabel').textContent = result.pages ? `${page} / ${result.pages}` : 'Просмотр недоступен';
        $('filledPrev').disabled = page <= 1;
        $('filledNext').disabled = page >= result.pages;
        const image = document.createElement('img');
        image.alt = `Заполненный результат, страница ${page}`;
        if (result.pages) image.src = `/api/generate/results/${encodeURIComponent(result.id)}/pages/${page}`;
        image.onerror = () => note('Страница недоступна. Скачайте файл для проверки.');
        $('filledCanvas').replaceChildren(...(result.pages ? [image] : []));
        $('filledDownload').href = result.download;
        $('filledDownload').download = result.filename;
        $('filledDownload').textContent = result.draft ? 'Скачать черновик' : 'Скачать просмотренный файл';
    }
    function schedule(delay = 500) {
        clearTimeout(timer);
        if (active) timer = setTimeout(update, delay);
    }
    async function update() {
        if (busy || !active) return;
        const kind = mode;
        const params = kind === 'source' ? {} : getParams();
        if (params === null) { note('Исправьте данные или дождитесь чтения изображения.'); return; }
        const token = version;
        busy = true;
        $('filledDownload').hidden = true;
        note(kind === 'pages' ? 'Создаём файл и проверяем страницы…' : 'Обновляем черновик…');
        const form = new FormData();
        form.set('template', $('template').value);
        form.set('params', JSON.stringify(params));
        if (kind === 'pages') {
            form.set('preview', 'true');
            form.set('format', $('formatGroup').querySelector('.active').dataset.format);
            form.set('output', $('output').value || 'output.docx');
        } else form.set('source', String(kind === 'source'));
        try {
            const data = await window.api(kind === 'pages' ? '/api/generate' : '/api/generate/live-preview', {method: 'POST', formData: form});
            if (token !== version) return;
            if (!data.success) { renderErrors(data.errors); note(data.error || 'Просмотр недоступен. Можно создать и скачать документ.'); return; }
            if (kind === 'pages') {
                result = data; page = 1; renderPages(); $('filledDownload').hidden = false;
                const status = data.draft ? 'Черновик. Осталось заполнить: ' + data.missing_fields.map(field => field.label).join(', ')
                    : 'Файл создан. Скачивание выдаёт именно этот результат.';
                note(status + (!data.available ? ' Просмотр страниц недоступен. Скачайте созданный файл для проверки.' : ''));
            } else {
                // Документ отображается в изолированной рамке без скриптов и внешних запросов.
                const guard = `<meta http-equiv="Content-Security-Policy" content="${policy}">`;
                $('livePreviewFrame').srcdoc = data.html.replace(/<head[^>]*>/i, match => match + guard).replace(/<\/head>/i, draftStyle + '</head>');
                $('livePreviewFrame').hidden = false;
                note(data.draft ? 'Осталось заполнить: ' + data.missing_fields.map(field => field.label).join(', ') : '');
            }
        } catch (error) { if (token === version) note(error.message); }
        finally { busy = false; if (token !== version) schedule(0); }
    }
    function choose(value) { mode = value; version++; clearTimeout(timer); show(); update(); }
    $('previewFilled').onclick = () => choose('live');
    $('previewSource').onclick = () => choose('source');
    $('previewAccurate').onclick = () => choose('pages');
    $('filledPrev').onclick = () => { if (page > 1) { page--; renderPages(); } };
    $('filledNext').onclick = () => { if (result && page < result.pages) { page++; renderPages(); } };
    return {
        invalidate() {
            version++; $('filledDownload').hidden = true;
            if (!active || editing || mode === 'source') return;
            mode = 'live'; show(); note('Данные изменились. Обновляем черновик…'); schedule();
        },
        ready() { active = true; mode = editing ? 'source' : 'live'; show(); schedule(); },
        setEditing(value) {
            if (value) beforeEdit = mode;
            editing = value;
            mode = value ? 'source' : beforeEdit === 'source' ? 'source' : 'live';
            version++; clearTimeout(timer); show(); schedule();
        },
        reset() {
            version++; active = false; clearTimeout(timer); result = null;
            $('filledDownload').hidden = true; $('filledCanvas').replaceChildren();
            $('livePreviewFrame').hidden = true; $('livePreviewFrame').removeAttribute('srcdoc');
            $('livePreviewStatus').textContent = 'Выберите шаблон для просмотра.';
        },
    };
}
