"use strict";

const version = new URL(import.meta.url).search;
const {createOcrEditor} = await import('./recognize/editor.js' + version);
const {createIngestInput} = await import('../components/ingest-input.js' + version);
const $ = id => document.getElementById(id);
const resultArea = $('result');
const editor = createOcrEditor($, setStatus);
let busy = false;

function setStatus(message, type) {
    const element = $('status');
    element.hidden = !message;
    element.className = 'status-bar ' + (type || 'info');
    element.textContent = message;
}

function syncScenario(file = input.getFile()) {
    const image = file && !file.name.toLowerCase().endsWith('.pdf');
    $('scenarioOptions').hidden = Boolean(image);
    const hints = {
        fast: 'Извлекаем только существующий текст. OCR-движок не требуется; текст изображений пропускается.',
        structure: 'Сохраняем существующий текст, OCR используется для сканов при наличии движка.',
        scan: 'Требуется установленный OCR-движок. Распознаём все страницы, даже если текстовый слой уже есть.',
    };
    $('scenarioHint').textContent = image ? 'Для изображения используется OCR. Требуется установленный движок распознавания.' : hints[$('scenario').value];
}

const input = createIngestInput($, setStatus, {extensions: ['.png', '.jpg', '.jpeg', '.pdf'], onSelected: syncScenario});
$('scenario').addEventListener('change', () => syncScenario());

async function process() {
    const file = input.getFile();
    if (!file || busy || !editor.canReplace()) return;
    busy = true;
    editor.setBusy(true);
    input.setBusy(true);
    setStatus(`Обрабатываем «${file.name}»…`, 'info');
    const form = new FormData();
    form.append('file', file);
    form.append('lang', $('lang').value);
    form.append('gpu', $('gpu').checked ? 'true' : 'false');
    form.append('mode', $('mode').value);
    form.append('scenario', file.name.toLowerCase().endsWith('.pdf') ? $('scenario').value : 'scan');
    try {
        const data = await window.api('/api/recognize', {method: 'POST', formData: form});
        if (!data.success) throw new Error(data.error || 'Не удалось распознать файл.');
        editor.accept(data);
        const confidence = Number.isFinite(data.confidence) ? ` · уверенность ${(data.confidence * 100).toFixed(1)}%` : '';
        setStatus(`Текст готов к проверке${confidence}`, 'success');
        resultArea.focus({preventScroll: false});
    } catch (error) {
        setStatus(error.message || 'Не удалось распознать файл. Файл и настройки сохранены — повторите обработку.', 'error');
    } finally {
        editor.setBusy(false);
        input.setBusy(false);
        busy = false;
    }
}

$('processBtn').addEventListener('click', process);
$('copyBtn').addEventListener('click', async () => {
    if (!resultArea.value) return;
    try { await navigator.clipboard.writeText(resultArea.value); }
    catch (_) { resultArea.select(); document.execCommand('copy'); }
    window.toast('Текст скопирован', 'success');
});
