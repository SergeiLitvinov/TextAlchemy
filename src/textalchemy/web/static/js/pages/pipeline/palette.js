"use strict";
const {groupLabel, operationLabel} = await import('./labels.js' + new URL(import.meta.url).search);

export function createOperationPalette($, model, onAdd) {
    function render() {
        const search = ($('opSearch').value || '').toLowerCase().trim();
        const grouped = {};
        for (const operation of model.state.operations) {
            const haystack = `${operationLabel(operation.id)} ${operation.id} ${operation.description}`.toLowerCase();
            if (search && !haystack.includes(search)) continue;
            const tag = operation.tags?.[0] || 'other';
            (grouped[tag] ||= []).push(operation);
        }
        $('opsCount').textContent = Object.values(grouped).reduce((total, group) => total + group.length, 0);
        $('opsPalette').innerHTML = Object.keys(grouped).sort().map((tag) =>
            `<details class="operation-group" ${search ? 'open' : ''}><summary>${window.esc(groupLabel(tag))} · ${grouped[tag].length}</summary>` + grouped[tag].map((operation) => `
                <button type="button" class="op-chip" data-op="${window.esc(operation.id)}" title="${window.esc(operation.description)}">
                    <strong>${window.esc(operationLabel(operation.id))}</strong>
                    <span class="op-types">${window.esc(operation.id)}</span>
                </button>`).join('') + '</details>'
        ).join('') || '<p class="hint">Ничего не найдено.</p>';
    }

    $('opSearch').addEventListener('input', render);
    $('opsPalette').addEventListener('click', (event) => {
        const button = event.target.closest('[data-op]');
        if (button) onAdd(button.dataset.op);
    });
    return {render};
}
