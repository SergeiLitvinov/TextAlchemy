"use strict";

export function createOperationPalette($, model, onAdd) {
    function render() {
        const search = ($('opSearch').value || '').toLowerCase().trim();
        const grouped = {};
        for (const operation of model.state.operations) {
            const haystack = `${operation.id} ${operation.description}`.toLowerCase();
            if (search && !haystack.includes(search)) continue;
            const tag = operation.tags?.[0] || 'other';
            (grouped[tag] ||= []).push(operation);
        }
        $('opsCount').textContent = Object.values(grouped).reduce((total, group) => total + group.length, 0);
        $('opsPalette').innerHTML = Object.keys(grouped).sort().map((tag) =>
            `<h4 class="ops-tag">${window.esc(tag)}</h4>` + grouped[tag].map((operation) => `
                <button type="button" class="op-chip" data-op="${window.esc(operation.id)}" title="${window.esc(operation.description)}">
                    <code>${window.esc(operation.id)}</code>
                    <span class="op-types">${window.esc(operation.input_type || '—')} → ${window.esc(operation.output_type || '?')}</span>
                </button>`).join('')
        ).join('') || '<p class="hint">Ничего не найдено.</p>';
    }

    $('opSearch').addEventListener('input', render);
    $('opsPalette').addEventListener('click', (event) => {
        const button = event.target.closest('[data-op]');
        if (button) onAdd(button.dataset.op);
    });
    return {render};
}
