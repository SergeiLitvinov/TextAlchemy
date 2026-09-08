"use strict";

const activeStates = new Set(['queued', 'running', 'cancelling']);

export function createBatchFilter($, render) {
    let tasks = [];
    let currentJob = null;

    function refresh() {
        const state = $('batchStateFilter').value;
        const query = $('batchNameFilter').value.trim().toLocaleLowerCase();
        const visible = tasks.filter((task) => {
            const matchesState = state === 'all' ||
                (state === 'active' && activeStates.has(task.status)) ||
                (state === 'done' && task.status === 'done') ||
                (state === 'attention' && !activeStates.has(task.status) && task.status !== 'done');
            return matchesState && String(task.name || '').toLocaleLowerCase().includes(query);
        });
        render(visible);
        $('batchFilterSummary').textContent = `Показано ${visible.length} из ${tasks.length} файлов.`;
        $('batchFilterEmpty').hidden = visible.length > 0;
    }

    $('batchStateFilter').addEventListener('change', refresh);
    $('batchNameFilter').addEventListener('input', refresh);
    $('batchFilterReset').addEventListener('click', () => {
        $('batchStateFilter').value = 'all';
        $('batchNameFilter').value = '';
        refresh();
    });

    return {
        update(jobId, items) {
            if (jobId !== currentJob) {
                $('batchStateFilter').value = 'all';
                $('batchNameFilter').value = '';
                currentJob = jobId;
            }
            tasks = items;
            refresh();
        },
    };
}
