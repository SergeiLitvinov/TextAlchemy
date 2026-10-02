"use strict";

export function createIngestInput($, setStatus, {extensions, onSelected = () => {}}) {
    let file = null;
    let busy = false;
    const dropZone = $('dropZone');
    const input = $('fileInput');
    const action = $('processBtn');

    function select(next) {
        if (!next || busy) return;
        if (!extensions.some(extension => next.name.toLowerCase().endsWith(extension))) {
            setStatus('Этот формат не поддерживается. Выберите файл из списка над кнопкой.', 'error');
            input.value = '';
            return;
        }
        file = next;
        $('selectedFile').textContent = `${file.name} · ${Math.max(1, Math.ceil(file.size / 1024))} КБ`;
        $('selectedFile').hidden = false;
        action.disabled = false;
        onSelected(file);
        setStatus('Файл выбран. Проверьте настройки и начните обработку.', 'info');
    }

    function setBusy(value) {
        busy = value;
        action.disabled = busy || !file;
        input.disabled = busy;
        dropZone.setAttribute('aria-disabled', String(busy));
        dropZone.classList.toggle('is-processing', busy);
        $('inputOptions').querySelectorAll('select, input, button').forEach(control => { control.disabled = busy; });
    }

    dropZone.addEventListener('click', () => { if (!busy) input.click(); });
    dropZone.addEventListener('keydown', event => {
        if (!busy && ['Enter', ' '].includes(event.key)) { event.preventDefault(); input.click(); }
    });
    dropZone.addEventListener('dragover', event => {
        event.preventDefault();
        if (!busy) dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', event => {
        event.preventDefault();
        dropZone.classList.remove('dragover');
        select(event.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => select(input.files[0]));
    setBusy(false);
    return {getFile: () => file, setBusy};
}
