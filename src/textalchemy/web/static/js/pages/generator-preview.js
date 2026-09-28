"use strict";
export function createGeneratedPreview($, getParams, renderErrors) {
    let version = 0, result = null, page = 1, busy = false, timer = null, active = false, source = false;
    const note = text => { $('filledPreviewStatus').textContent = text; };
    function show(filled) {
        $('filledPreview').hidden = !filled;
        $('previewCanvas').hidden = filled;
        $('previewPaging').hidden = filled || !$('previewCanvas').querySelector('img');
        $('preview-title').textContent = filled ? 'Заполненный результат' : 'Страницы шаблона';
        $('previewNote').hidden = filled;
    }
    function render() {
        $('filledPageLabel').textContent = result.pages ? `${page} / ${result.pages}` : 'Просмотр недоступен';
        $('filledPrev').disabled = page <= 1; $('filledNext').disabled = page >= result.pages;
        const image = document.createElement('img'); image.alt = `Заполненный результат, страница ${page}`;
        if (result.pages) image.src = `/api/generate/results/${encodeURIComponent(result.id)}/pages/${page}`;
        image.onerror = () => note('Страница недоступна. Вернитесь к предпросмотру или скачайте файл.');
        $('filledCanvas').replaceChildren(...(result.pages ? [image] : []));
        $('filledDownload').href = result.download;
        $('filledDownload').download = result.filename;
        $('filledDownload').textContent = result.draft ? 'Скачать черновик' : 'Скачать просмотренный файл';
    }
    function schedule() {
        clearTimeout(timer);
        if (active && !source) timer = setTimeout(update, 1200);
    }
    async function update() {
        if (busy || !active || source) return;
        const params = getParams();
        if (params === null) { note('Исправьте данные или дождитесь загрузки изображения: просмотр обновится автоматически.'); return; }
        const token = version; busy = true;
        renderErrors(null); $('filledDownload').hidden = true;
        note('Создаём предпросмотр…'); show(true);
        const form = new FormData(); form.set('template', $('template').value);
        form.set('params', JSON.stringify(params)); form.set('preview', 'true');
        form.set('format', $('formatGroup').querySelector('.active').dataset.format);
        form.set('output', $('output').value || 'output.docx');
        try {
            const data = await window.api('/api/generate', {method: 'POST', formData: form});
            if (token !== version) return;
            if (!data.success) { renderErrors(data.errors); note(data.error || 'Не удалось создать документ.'); $('previewFilled').hidden = false; return; }
            result = data; page = 1; render(); $('previewFilled').hidden = true; $('filledDownload').hidden = false;
            $('preview-title').textContent = data.draft ? 'Черновой просмотр' : 'Заполненный результат';
            const availability = data.available ? '' : ' Просмотр страниц недоступен; скачайте файл для проверки.';
            note(data.draft ? 'Черновик. Осталось заполнить: ' + data.missing_fields.map(field => field.label).join(', ') +
                '. Пустые текстовые места отмечены в документе; незаданные списки считаются пустыми, флажки — выключенными.' + availability
                : 'Просмотр созданного файла. Скачивание выдаёт этот же результат; хранится один час.' + availability);
        } catch (error) { if (token === version) { note(error.message); $('previewFilled').hidden = false; } }
        finally { busy = false; if (token !== version) schedule(); }
    }
    $('previewFilled').onclick = () => { source = false; clearTimeout(timer); update(); };
    $('previewSource').onclick = () => { source = true; version++; clearTimeout(timer); $('previewFilled').hidden = false; show(false); };
    $('filledPrev').onclick = () => { if (page > 1) { page--; render(); } };
    $('filledNext').onclick = () => { if (result && page < result.pages) { page++; render(); } };
    return {
        invalidate() { version++; if (active) { note('Данные изменились. Предпросмотр обновится автоматически…'); $('filledDownload').hidden = true; } schedule(); },
        ready() { active = true; source = false; show(true); note('Предпросмотр обновляется автоматически после паузы во вводе.'); schedule(); },
        reset() { version++; active = false; source = false; clearTimeout(timer); result = null; $('previewFilled').hidden = true; $('filledDownload').hidden = true; $('filledCanvas').replaceChildren(); show(false); },
    };
}
