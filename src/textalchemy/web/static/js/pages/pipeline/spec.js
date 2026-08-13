"use strict";

function normalize(value) {
    if (value === '' || value === undefined || value === null) return undefined;
    if (typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (/^-?\d+$/.test(trimmed)) return Number(trimmed);
    if (/^-?\d*\.\d+$/.test(trimmed)) return Number.parseFloat(trimmed);
    if (trimmed === 'true' || trimmed === 'false') return trimmed === 'true';
    if (/^[\[{]/.test(trimmed) && /[\]}]$/.test(trimmed)) {
        try { return JSON.parse(trimmed); } catch (_) { /* keep user text */ }
    }
    return value;
}

export function buildSpecification(state) {
    let specification = {};
    if (state.contextJson.trim()) {
        try { specification = JSON.parse(state.contextJson); }
        catch (error) { throw new Error(`Некорректный JSON контекста: ${error.message}`); }
        if (!specification || Array.isArray(specification) || typeof specification !== 'object') {
            throw new Error('Начальные данные должны быть JSON-объектом.');
        }
    }
    specification.steps = state.steps.map((step) => {
        const result = {};
        if (step.op) result.op = step.op;
        if (step.output) result.output = step.output;
        if (step.input) result.input = step.input;
        const params = Object.fromEntries(Object.entries(step.params).flatMap(([name, value]) => {
            const normalized = normalize(value);
            return normalized === undefined ? [] : [[name, normalized]];
        }));
        if (Object.keys(params).length) result.params = params;
        return result;
    });
    if (state.finalOutput) specification.output = state.finalOutput;
    return specification;
}

export function specificationJson(state) {
    return JSON.stringify(buildSpecification(state));
}
