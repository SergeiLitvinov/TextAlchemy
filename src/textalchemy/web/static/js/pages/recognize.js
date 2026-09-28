"use strict";

import {createOcrEditor} from './recognize/editor.js';

const $ = (id) => document.getElementById(id);
const dropZone = $('dropZone');
const fileInput = $('fileInput');
const resultArea = $('result');
const editor = createOcrEditor($, setStatus);

function setStatus(message, type) {
    const element = $('status');
    element.hidden = !message;
    if (!message) return;
    element.className = 'status-bar ' + (type || 'info');
    element.textContent = message;
}

function selectScenario(button) {
    document.querySelectorAll('.scenario-option').forEach((option) => {
        const selected = option === button;
        option.classList.toggle('active', selected);
        option.setAttribute('aria-checked', String(selected));
    });
    $('scenario').value = button.dataset.scenario;
}

document.querySelectorAll('.scenario-option').forEach((button) => {
    button.addEventListener('click', () => selectScenario(button));
});

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        fileInput.click();
    }
});
dropZone.addEventListener('dragover', (event) => {
    event.preventDefault();
    dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (event) => {
    event.preventDefault();
    dropZone.classList.remove('dragover');
    if (event.dataTransfer.files[0]) handleFile(event.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

async function handleFile(file) {
    if (!editor.canReplace()) return;
    editor.setBusy(true);
    setStatus(`Обрабатываем «${file.name}»…`, 'info');
    dropZone.classList.add('is-processing');
    const form = new FormData();
    form.append('file', file);
    form.append('lang', $('lang').value);
    form.append('gpu', $('gpu').checked ? 'true' : 'false');
    form.append('mode', $('mode').value);
    form.append('scenario', $('scenario').value);
    try {
        const data = await api('/api/recognize', {method: 'POST', formData: form});
        if (!data.success) throw new Error(data.error || 'Не удалось распознать файл.');
        editor.accept(data);
        const confidence = data.confidence ? ` · уверенность ${(data.confidence * 100).toFixed(1)}%` : '';
        setStatus(`Обработка завершена${confidence}`, 'success');
        toast('Текст готов к проверке', 'success');
    } catch (error) {
        setStatus(error.message || 'Не удалось распознать файл. Проверьте формат и настройки.', 'error');
    } finally {
        dropZone.classList.remove('is-processing');
        editor.setBusy(false);
    }
}

$('copyBtn').addEventListener('click', async () => {
    if (!resultArea.value) {
        toast('Нечего копировать', 'warning');
        return;
    }
    try {
        await navigator.clipboard.writeText(resultArea.value);
        toast('Текст скопирован', 'success');
    } catch (_) {
        resultArea.select();
        document.execCommand('copy');
        toast('Текст скопирован', 'success');
    }
});
