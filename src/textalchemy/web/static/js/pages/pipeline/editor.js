"use strict";

export function createStepEditor($, model, onChange) {
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
            control = `<input type="${type}"${stepAttribute} id="${id}" data-name="${window.esc(name)}" value="${window.esc(step.params[name] ?? '')}"${hint}>`;
        }
        return `<div class="param-field"><label for="${id}">${window.esc(name)}${info.required ? ' <span class="req">*</span>' : ''}</label>${control}</div>`;
    }

    function renderOutputs() {
        const names = model.knownNames();
        const current = model.state.finalOutput || model.state.steps.at(-1)?.output || '';
        $('finalOutput').innerHTML = ['<option value="">— последний шаг —</option>']
            .concat(names.map((name) => `<option value="${window.esc(name)}" ${name === current ? 'selected' : ''}>${window.esc(name)}</option>`)).join('');
        if (model.state.finalOutput) $('finalOutput').value = model.state.finalOutput;
    }

    function renderSteps() {
        const names = model.knownNames();
        if (!model.state.steps.length) {
            $('stepsList').innerHTML = '<p class="hint">Добавьте шаг: выберите операцию справа или нажмите «Добавить шаг».</p>';
            return;
        }
        $('stepsList').innerHTML = model.state.steps.map((step, index) => {
            const operation = model.state.operationMap.get(step.op);
            const operations = model.state.operations.map((item) =>
                `<option value="${window.esc(item.id)}" ${item.id === step.op ? 'selected' : ''}>${window.esc(item.id)}</option>`).join('');
            const inputs = ['<option value="">— нет —</option>'].concat(names.filter((name) => name !== step.output).map((name) =>
                `<option value="${window.esc(name)}" ${name === step.input ? 'selected' : ''}>${window.esc(name)}</option>`)).join('');
            let params = '<span class="hint">Параметры не требуются.</span>';
            if (operation) {
                const names = Object.keys(operation.params).filter((name) => !(step.input && name === operation.input_param));
                if (names.length) params = names.map((name) => parameterControl(step, operation, name, index)).join('');
            }
            return `<div class="step-card" data-index="${index}">
                <div class="step-head"><select class="op-select" data-field="op" aria-label="Операция">${operations}</select>
                    <div class="btn-group step-actions"><button type="button" class="btn btn-sm" data-move="-1" aria-label="Выше">↑</button>
                    <button type="button" class="btn btn-sm" data-move="1" aria-label="Ниже">↓</button>
                    <button type="button" class="btn btn-sm btn-danger" data-remove aria-label="Удалить">✕</button></div></div>
                <div class="step-body"><div class="param-field"><label for="output-${index}">Выход (переменная)</label>
                    <input type="text" id="output-${index}" data-field="output" value="${window.esc(step.output)}" placeholder="doc"></div>
                    <div class="param-field"><label for="input-${index}">Вход (из контекста)</label>
                    <select id="input-${index}" data-field="input">${inputs}</select></div><div class="step-params">${params}</div></div></div>`;
        }).join('');
    }

    function render() { renderSteps(); renderOutputs(); }

    $('stepsList').addEventListener('input', (event) => {
        const card = event.target.closest('.step-card');
        if (!card) return;
        const step = model.state.steps[Number(card.dataset.index)];
        if (event.target.dataset.field === 'output') { step.output = event.target.value.trim(); renderOutputs(); }
        if (event.target.dataset.field === 'input') {
            step.input = event.target.value;
            step.params = model.defaultsFor(step.op, step.input, step.params);
            render();
        }
        onChange();
    });
    $('stepsList').addEventListener('change', (event) => {
        const card = event.target.closest('.step-card');
        if (!card) return;
        const index = Number(card.dataset.index);
        const step = model.state.steps[index];
        if (event.target.classList.contains('op-select')) { model.changeOperation(index, event.target.value); render(); }
        else if (event.target.dataset.name !== undefined) step.params[event.target.dataset.name] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
        onChange();
    });
    $('stepsList').addEventListener('click', (event) => {
        const card = event.target.closest('.step-card');
        if (!card) return;
        const index = Number(card.dataset.index);
        if (event.target.closest('[data-remove]')) model.removeStep(index);
        else {
            const move = event.target.closest('[data-move]');
            if (!move || !model.moveStep(index, Number(move.dataset.move))) return;
        }
        render(); onChange();
    });
    $('finalOutput').addEventListener('change', (event) => { model.state.finalOutput = event.target.value; $('customOutput').value = ''; onChange(); });
    $('customOutput').addEventListener('input', (event) => { model.state.finalOutput = event.target.value.trim(); $('finalOutput').value = ''; onChange(); });
    $('ctxText').addEventListener('input', (event) => { model.state.contextJson = event.target.value; renderOutputs(); onChange(); });

    return {render, renderSteps, renderOutputs};
}
