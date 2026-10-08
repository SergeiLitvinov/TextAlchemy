"use strict";

const {createIngestInput} = await import('../components/ingest-input.js' + new URL(import.meta.url).search);
const $ = id => document.getElementById(id);
const resultArea = $('result');
let download = null;
let busy = false;

function setStatus(message, type) {
    const element = $('status');
    element.hidden = !message;
    element.className = 'status-bar ' + (type || 'info');
    element.textContent = message;
}

const input = createIngestInput($, setStatus, {extensions: ['.pdf', '.docx', '.txt', '.djvu']});

async function process() {
    const file = input.getFile();
    if (!file || busy) return;
    const output = $('output-kind').value;
    if (output === 'latex' && !file.name.toLowerCase().endsWith('.docx')) {
        setStatus('LaTeX можно извлечь только из документа Word (DOCX). Выберите Word или результат «Чистый текст».', 'error');
        return;
    }
    busy = true;
    input.setBusy(true);
    setStatus(`Извлекаем содержимое из «${file.name}»…`, 'info');
    const form = new FormData();
    form.append('file', file);
    try {
        let text;
        if (output === 'latex') {
            form.append('doc_type', 'manuscript');
            const response = await fetch('/api/extract/latex', {method: 'POST', body: form});
            if (response.headers.get('Content-Type')?.includes('application/json')) {
                const error = await response.json();
                throw new Error(error.error || error.detail || 'Не удалось извлечь LaTeX.');
            }
            if (!response.ok) throw new Error('Не удалось извлечь LaTeX. Проверьте документ Word.');
            text = await response.text();
        } else {
            form.append('fmt', $('input-fmt').value);
            const data = await window.api('/api/extract/text', {method: 'POST', formData: form});
            if (!data.success) throw new Error(data.error || 'Не удалось извлечь текст.');
            text = data.text;
        }
        resultArea.value = text;
        resultArea.hidden = false;
        $('resultEmpty').hidden = true;
        $('resultTools').hidden = false;
        $('emptyTextHint').hidden = Boolean(text.trim());
        resultArea.classList.toggle('code-result', output === 'latex');
        $('extract-result-title').textContent = output === 'latex' ? 'Исходник LaTeX' : 'Извлечённый текст';
        $('resultSource').textContent = file.name;
        $('resultCard').hidden = false;
        $('ingestLayout').classList.add('has-result');
        download = {text, name: file.name.replace(/\.[^.]+$/, '') + (output === 'latex' ? '.tex' : '.txt')};
        setStatus(`Готово: ${text.length} символов. Исходник не изменён.`, 'success');
        resultArea.focus({preventScroll: false});
    } catch (error) {
        setStatus(error.message || 'Не удалось извлечь содержимое. Файл и настройки сохранены — повторите обработку.', 'error');
    } finally {
        busy = false;
        input.setBusy(false);
    }
}

$('processBtn').addEventListener('click', process);
$('downloadBtn').addEventListener('click', () => {
    if (!download) return;
    const url = URL.createObjectURL(new Blob([download.text], {type: 'text/plain;charset=utf-8'}));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = download.name;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('copyBtn').addEventListener('click', async () => {
    if (!resultArea.value) return;
    try { await navigator.clipboard.writeText(resultArea.value); }
    catch (_) { resultArea.select(); document.execCommand('copy'); }
    window.toast('Содержимое скопировано', 'success');
});
