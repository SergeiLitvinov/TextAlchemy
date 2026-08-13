"use strict";

export function createPipelineState() {
    const state = {
        operations: [],
        operationMap: new Map(),
        steps: [],
        contextJson: '',
        finalOutput: '',
    };

    function setOperations(operations) {
        state.operations = operations;
        state.operationMap = new Map(operations.map((operation) => [operation.id, operation]));
    }

    function defaultSteps() {
        if (state.steps.length) return;
        state.steps = [
            {op: 'ingest.file', output: 'doc', input: '', params: {path: 'input.txt'}},
            {op: 'extract.text', output: 'text', input: 'doc', params: {}},
            {op: 'render.latex', output: 'tex', input: 'text', params: {title: 'Demo'}},
        ];
        state.finalOutput = 'tex';
    }

    function knownNames() {
        const names = new Set();
        try { Object.keys(JSON.parse(state.contextJson || '{}')).forEach((name) => names.add(name)); }
        catch (_) { /* invalid context is reported when building the specification */ }
        state.steps.forEach((step) => { if (step.output) names.add(step.output); });
        return [...names];
    }

    function defaultsFor(operationId, input, existing = {}) {
        const operation = state.operationMap.get(operationId);
        if (!operation) return {...existing};
        return Object.fromEntries(Object.entries(operation.params).flatMap(([name, info]) => {
            if (name === operation.input_param && input) return [];
            const value = existing[name] ?? (info.default !== null ? info.default : '');
            return [[name, value]];
        }));
    }

    function addStep(operationId, values = {}) {
        const input = values.input || '';
        state.steps.push({
            op: operationId,
            output: values.output || '',
            input,
            params: defaultsFor(operationId, input, values.params || {}),
        });
    }

    function removeStep(index) { state.steps.splice(index, 1); }

    function moveStep(index, delta) {
        const target = index + delta;
        if (target < 0 || target >= state.steps.length) return false;
        [state.steps[index], state.steps[target]] = [state.steps[target], state.steps[index]];
        return true;
    }

    function changeOperation(index, operationId) {
        const step = state.steps[index];
        if (!step || step.op === operationId) return;
        step.op = operationId;
        step.params = defaultsFor(operationId, step.input, step.params);
    }

    function importSpec(spec) {
        state.steps = (spec.steps || []).map((step) => ({
            op: step.op || '',
            output: step.output || '',
            input: step.input || '',
            params: defaultsFor(step.op, step.input || '', step.params || {}),
        }));
        const context = spec.ctx || Object.fromEntries(
            Object.entries(spec).filter(([name]) => !['steps', 'output'].includes(name)),
        );
        state.contextJson = Object.keys(context).length ? JSON.stringify(context, null, 2) : '';
        state.finalOutput = spec.output || '';
    }

    return {state, setOperations, defaultSteps, knownNames, defaultsFor, addStep, removeStep, moveStep, changeOperation, importSpec};
}
