"use strict";

const $ = (id) => document.getElementById(id);
const dropZone = $('dropZone');
const fileInput = $('fileInput');
const resultArea = $('result');

function setStatus(message, type) {
    const element = $('status');
    element.hidden = !message;
    if (!message) return;
    element.className = 'status-bar ' + (type || 'info');
    element.textContent = message;
}

function selectOutput(button) {
    document.querySelectorAll('.output-option').forEach((option) => {
        const selected = option === button;
        option.classList.toggle('active', selected);
        option.setAttribute('aria-checked', String(selected));
    });
    $('output-kind').value = button.dataset.output;
    $('extract-result-title').textContent = button.dataset.output === 'latex' ? 'Исходник LaTeX' : 'Извлечённый текст';
}

document.querySelectorAll('.output-option').forEach((button) => button.addEventListener('click', () => selectOutput(button)));
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); }
});
dropZone.addEventListener('dragover', (event) => { event.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragover');
    if (event.dataTransfer.files[0]) handleFile(event.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

function showText(text) {
    resultArea.value = text;
    resultArea.hidden = false;
    $('resultEmpty').hidden = true;
    $('copyBtn').disabled = false;
}

async function handleFile(file) {
    const output = $('output-kind').value;
    if (output === 'latex' && !file.name.toLowerCase().endsWith('.docx')) {
        setStatus('LaTeX можно извлечь только из документа Word (DOCX).', 'error');
        return;
    }
    setStatus(`Извлекаем содержимое из «${file.name}»…`, 'info');
    const form = new FormData();
    form.append('file', file);
    try {
        if (output === 'latex') {
            form.append('doc_type', 'manuscript');
            const response = await fetch('/api/extract/latex', {method: 'POST', body: form});
            const text = await response.text();
            if (!response.ok) throw new Error('LaTeX extraction failed');
            showText(text);
            setStatus(`LaTeX извлечён из «${file.name}»`, 'success');
        } else {
            form.append('fmt', $('input-fmt').value);
            const data = await api('/api/extract/text', {method: 'POST', formData: form});
            showText(data.text);
            setStatus(`Извлечено ${data.text.length} символов из «${data.filename}»`, 'success');
        }
        toast('Содержимое готово', 'success');
    } catch (_) {
        setStatus('Не удалось извлечь содержимое. Проверьте файл и выбранный результат.', 'error');
    }
}

$('copyBtn').addEventListener('click', async () => {
    if (!resultArea.value) return;
    try {
        await navigator.clipboard.writeText(resultArea.value);
        toast('Содержимое скопировано', 'success');
    } catch (_) {
        resultArea.select();
        document.execCommand('copy');
        toast('Содержимое скопировано', 'success');
    }
});
