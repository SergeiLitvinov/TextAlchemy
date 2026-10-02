"use strict";
const {operationLabel, parameterLabel} = await import('./labels.js' + new URL(import.meta.url).search);

export function createStepEditor($, model, onChange, onUploadBusy = () => {}) {
    async function uploadFile(input, step, name) {
        const file = input.files[0];
        if (!file) return;
        const field = input.closest('.param-field');
        const note = field.querySelector('[data-upload-status]');
        const retry = field.querySelector('[data-retry-upload]');
        onUploadBusy(true);
        retry.hidden = true;
        note.textContent = `Загрузка ${file.name}…`;
        try {
            const form = new FormData(); form.set('file', file);
            const data = await window.api('/api/pipeline/files', {method: 'POST', formData: form});
            if (model.state.steps.includes(step) && name in step.params) {
                step.params[name] = data.value;
                field.querySelector('[data-name]').value = data.value;
                note.textContent = `${data.name} загружен. Доступен один час.`;
                onChange();
            }
        } catch (error) {
            note.textContent = `${file.name}: ${error.message}. Текущий путь шага не изменён.`;
            retry.hidden = false;
        } finally { onUploadBusy(false); }
    }
    function parameterControl(step, operation, name, index) {
        const info = operation.params[name] || {default: null, required: false, annotation: ''};
        if (name === operation.input_param && step.input) return '';
        const annotation = info.annotation || '';
        const isBoolean = annotation === 'bool' || typeof info.default === 'boolean';
        const isNumber = /^(int(eger)?|float|number)/.test(annotation) || typeof info.default === 'number';
        const id = `p-${index}-${name}`;
        let control;
        if (isBoolean) {
            const checked = step.params[name] === true || step.params[name] === 'true';
            control = `<label class="param-bool"><input type="checkbox" id="${id}" data-name="${window.esc(name)}" ${checked ? 'checked' : ''}> ${info.default === true ? 'вкл' : 'выкл'}</label>`;
        } else {
            const type = isNumber ? 'number' : 'text';
            const stepAttribute = isNumber ? ' step="any"' : '';
            const hint = !isNumber && (/list|dict|\[\]/.test(annotation) || /^[\[{]/.test(String(info.default ?? '')))
                ? ' placeholder="JSON, например [1,2]"' : '';
            const value = step.params[name];
            const display = value && typeof value === 'object' ? JSON.stringify(value) : value ?? '';
            control = `<input type="${type}"${stepAttribute} id="${id}" data-name="${window.esc(name)}" value="${window.esc(display)}"${hint}>`;
        }
        const upload = ['path', 'input_path'].includes(name) ? `<label for="${id}-file">Выбрать файл с компьютера</label><input id="${id}-file" type="file" data-upload="${window.esc(name)}"><small data-upload-status></small><button type="button" class="btn-secondary" data-retry-upload hidden>Повторить загрузку</button>` : '';
        const outputHelp = ['output_path', 'output_dir', 'output'].includes(name) ? '<small>Имя результата. Файл будет доступен для скачивания; запись в исходную папку не выполняется.</small>' : '';
        return `<div class="param-field"><label for="${id}" title="${window.esc(name)}">${window.esc(parameterLabel(name))}${info.required ? ' <span class="req">*</span>' : ''}</label>${control}${upload}${outputHelp}</div>`;
    }

    function renderOutputs() {
        const names = model.knownNames();
        const current = model.state.finalOutput || model.state.steps.at(-1)?.output || '';
        if (current && !names.includes(current)) names.push(current);
        $('finalOutput').innerHTML = ['<option value="">— последний шаг —</option>']
            .concat(names.map((name) => `<option value="${window.esc(name)}" ${name === current ? 'selected' : ''}>${window.esc(name)}</option>`)).join('');
        if (model.state.finalOutput) $('finalOutput').value = model.state.finalOutput;
    }

    function renderSteps() {
        if (!model.state.steps.length) {
            $('stepsList').innerHTML = '<p class="hint">Выберите действие в каталоге «Добавить шаг».</p>';
            return;
        }
        $('stepsList').innerHTML = model.state.steps.map((step, index) => {
            const operation = model.state.operationMap.get(step.op);
            const operations = model.state.operations.map((item) =>
                `<option value="${window.esc(item.id)}" ${item.id === step.op ? 'selected' : ''}>${window.esc(operationLabel(item.id))}</option>`).join('');
            const unavailable = operation ? '' : `<option selected value="${window.esc(step.op)}">Недоступное действие — ${window.esc(step.op)}</option>`;
            const names = model.knownNames(index);
            const missing = step.input && !names.includes(step.input);
            const inputLabel = name => {
                const source = model.state.steps.slice(0, index).findLastIndex(item => item.output === name);
                return source < 0 ? `Начальные данные — ${name}` : `Шаг ${source + 1}: ${operationLabel(model.state.steps[source].op)} — ${name}`;
            };
            const inputs = ['<option value="">Ввести параметры ниже</option>'].concat(names.map((name) =>
                `<option value="${window.esc(name)}" ${name === step.input ? 'selected' : ''}>${window.esc(inputLabel(name))}</option>`),
                missing ? [`<option selected value="${window.esc(step.input)}">Недоступный источник — ${window.esc(step.input)}</option>`] : []).join('');
            let params = '<span class="hint">Параметры не требуются.</span>';
            if (operation) {
                const names = Object.keys(operation.params).filter((name) => !(step.input && name === operation.input_param));
                if (names.length) {
                    const required = names.filter(name => operation.params[name].required);
                    const optional = names.filter(name => !operation.params[name].required);
                    params = required.map(name => parameterControl(step, operation, name, index)).join('');
                    if (optional.length) params += `<details class="workspace-disclosure step-extra"><summary>Дополнительные параметры (${optional.length})</summary><div class="step-params">${optional.map(name => parameterControl(step, operation, name, index)).join('')}</div></details>`;
                }
            }
            return `<div class="step-card" data-index="${index}">
                <div class="step-head"><select class="op-select" data-field="op" aria-label="Операция">${operations}${unavailable}</select>
                    <div class="btn-group step-actions"><button type="button" class="btn btn-sm" data-move="-1" aria-label="Выше" ${index === 0 ? 'disabled' : ''}>↑</button>
                    <button type="button" class="btn btn-sm" data-move="1" aria-label="Ниже" ${index === model.state.steps.length - 1 ? 'disabled' : ''}>↓</button>
                    <button type="button" class="btn btn-sm btn-danger" data-remove aria-label="Удалить">✕</button></div></div>
                <p class="field-help">${window.esc(operation?.description || step.op)}</p>
                <div class="step-body"><div class="param-field"><label for="output-${index}">Назвать результат шага</label>
                    <input type="text" id="output-${index}" data-field="output" value="${window.esc(step.output)}" placeholder="doc"></div>
                    <div class="param-field"><label for="input-${index}">Взять данные из</label>
                    <select id="input-${index}" data-field="input" aria-describedby="connection-${index}">${inputs}</select>
                    <p id="connection-${index}" class="field-help ${missing ? 'connection-error' : ''}">${missing ? 'Источник удалён, переименован или находится ниже. Выберите предыдущий шаг.' : 'Доступны начальные данные и результаты предыдущих шагов.'}</p></div><div class="step-params">${params}</div></div></div>`;
        }).join('');
    }

    function render() { renderSteps(); renderOutputs(); }

    $('stepsList').addEventListener('input', (event) => {
        const card = event.target.closest('.step-card');
        if (!card) return;
        const step = model.state.steps[Number(card.dataset.index)];
        if (event.target.dataset.name !== undefined) step.params[event.target.dataset.name] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
        if (event.target.dataset.field === 'output') { step.output = event.target.value.trim(); renderOutputs(); }
        if (event.target.dataset.field === 'input') {
            step.input = event.target.value;
            step.params = model.defaultsFor(step.op, step.input, step.params);
            render();
        }
        onChange();
    });
    $('stepsList').addEventListener('change', async (event) => {
        const card = event.target.closest('.step-card');
        if (!card) return;
        const index = Number(card.dataset.index);
        const step = model.state.steps[index];
        if (event.target.dataset.upload) {
            await uploadFile(event.target, step, event.target.dataset.upload);
            return;
        }
        if (event.target.classList.contains('op-select')) { model.changeOperation(index, event.target.value); render(); }
        else if (event.target.dataset.name !== undefined) step.params[event.target.dataset.name] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
        else if (event.target.dataset.field === 'output') render();
        onChange();
    });
    $('stepsList').addEventListener('click', (event) => {
        const card = event.target.closest('.step-card');
        if (!card) return;
        const index = Number(card.dataset.index);
        if (event.target.closest('[data-retry-upload]')) {
            const input = event.target.closest('.param-field').querySelector('[data-upload]');
            uploadFile(input, model.state.steps[index], input.dataset.upload);
            return;
        }
        if (event.target.closest('[data-remove]')) model.removeStep(index);
        else {
            const move = event.target.closest('[data-move]');
            if (!move || !model.moveStep(index, Number(move.dataset.move))) return;
        }
        render(); onChange();
    });
    $('finalOutput').addEventListener('change', (event) => { model.state.finalOutput = event.target.value; $('customOutput').value = ''; onChange(); });
    $('customOutput').addEventListener('input', (event) => { model.state.finalOutput = event.target.value.trim(); $('finalOutput').value = ''; onChange(); });
    $('ctxText').addEventListener('input', (event) => { model.state.contextJson = event.target.value; render(); onChange(); });

    return {render, renderSteps, renderOutputs};
}
