"use strict";

const {conversionApi} = await import('./api.js' + new URL(import.meta.url).search);

export function createPreviewController($, onCompletedTask) {
    let taskId = null;
    let meta = null;
    let mode = 'source';
    let page = 1;
    let requestId = 0;
    const urls = new Set();

    function clearImages() {
        for (const url of urls) URL.revokeObjectURL(url);
        urls.clear();
    }

    function imageUrl(blob) {
        const url = URL.createObjectURL(blob);
        urls.add(url);
        return url;
    }

    function availablePages() {
        if (mode === 'compare') return Math.min(meta?.source?.pages || 0, meta?.target?.pages || 0);
        if (mode === 'diff') return Math.min(meta?.source?.pages || 0, meta?.target?.pages || 0);
        return meta?.[mode]?.pages || 0;
    }

    function syncControls() {
        const source = Boolean(meta?.source?.available);
        const target = Boolean(meta?.target?.available);
        if (mode === 'source' && !source) mode = target ? 'target' : 'source';
        if (mode === 'target' && !target) mode = source ? 'source' : 'target';
        if (['compare', 'diff'].includes(mode) && !(source && target)) mode = 'source';
        $('previewModeSource').disabled = !source;
        $('previewModeTarget').disabled = !target;
        $('previewModeCompare').disabled = !source || !target;
        $('previewModeDiff').disabled = !source || !target;
        for (const [button, value] of [
            ['previewModeSource', 'source'], ['previewModeTarget', 'target'],
            ['previewModeCompare', 'compare'], ['previewModeDiff', 'diff'],
        ]) {
            $(button).classList.toggle('active', mode === value);
        }
        const pages = availablePages();
        if (page > pages) page = Math.max(1, pages);
        $('previewPageLabel').textContent = pages ? `${page} / ${pages}` : '—';
        $('previewPrev').disabled = !pages || page <= 1;
        $('previewNext').disabled = !pages || page >= pages;
    }

    async function render() {
        const currentRequest = ++requestId;
        const canvas = $('previewCanvas');
        clearImages();
        canvas.innerHTML = '<p class="field-help" id="previewMessage">Рендерим страницы…</p>';
        syncControls();
        if (mode === 'diff') {
            try {
                const result = await conversionApi.previewDiff(taskId, page);
                if (currentRequest !== requestId) return;
                const image = document.createElement('img');
                image.alt = 'Тепловая карта отличий исходника и результата';
                image.src = imageUrl(result.blob);
                canvas.innerHTML = '';
                const wrapper = document.createElement('div');
                wrapper.className = 'preview-single preview-diff';
                wrapper.appendChild(image);
                canvas.appendChild(wrapper);
                $('previewHint').textContent = Number.isFinite(result.similarity)
                    ? `Визуальное сходство страницы: ${Math.round(result.similarity * 100)}%. Красным подсвечены различия.`
                    : 'Красным подсвечены визуальные различия результата.';
            } catch (_) {
                if (currentRequest === requestId) canvas.innerHTML = '<p class="field-help">Не удалось построить карту различий.</p>';
            }
            return;
        }
        $('previewHint').textContent = 'Листайте стрелками ← →. В режиме «До / после» показываются одинаковые страницы.';
        const sides = mode === 'compare' ? ['source', 'target'] : [mode];
        try {
            const entries = await Promise.all(sides.map(async (side) => ({
                side, blob: await conversionApi.previewPage(taskId, side, page),
            })));
            if (currentRequest !== requestId) return;
            canvas.innerHTML = '';
            const wrapper = document.createElement('div');
            wrapper.className = mode === 'compare' ? 'preview-compare' : 'preview-single';
            for (const {side, blob} of entries) {
                const figure = document.createElement('figure');
                const image = document.createElement('img');
                image.alt = side === 'source' ? 'Страница исходника' : 'Страница результата';
                image.loading = 'lazy';
                image.src = imageUrl(blob);
                const caption = document.createElement('figcaption');
                caption.textContent = side === 'source' ? 'Исходник' : 'Результат';
                figure.append(image, caption);
                wrapper.appendChild(figure);
            }
            canvas.appendChild(wrapper);
        } catch (_) {
            if (currentRequest === requestId) canvas.innerHTML = '<p class="field-help">Не удалось отрисовать страницы.</p>';
        }
    }

    async function init(newTaskId) {
        taskId = newTaskId;
        meta = null;
        mode = 'source';
        page = 1;
        const currentRequest = ++requestId;
        clearImages();
        $('previewSection').hidden = true;
        if (!taskId) return;
        try {
            const nextMeta = await conversionApi.previewMeta(newTaskId);
            if (currentRequest !== requestId || newTaskId !== taskId) return;
            meta = nextMeta;
            if (!meta.source?.available && !meta.target?.available) return;
            $('previewSection').hidden = false;
            syncControls();
            render();
        } catch (_) {
            if (currentRequest === requestId) $('previewSection').hidden = true;
        }
    }

    async function open(newTaskId) {
        if (!newTaskId) return;
        const currentRequest = ++requestId;
        try {
            const data = await conversionApi.task(newTaskId);
            if (currentRequest !== requestId) return;
            if (data.status === 'done') {
                onCompletedTask(data, newTaskId);
                return;
            }
        } catch (_) { /* standalone preview remains useful */ }
        if (currentRequest !== requestId) return;
        await init(newTaskId);
        if (taskId === newTaskId) $('previewSection').scrollIntoView({behavior: 'smooth', block: 'center'});
    }

    function reset() {
        requestId += 1;
        taskId = null;
        meta = null;
        clearImages();
        $('previewSection').hidden = true;
    }

    function choose(nextMode) { mode = nextMode; syncControls(); render(); }
    $('previewModeSource').addEventListener('click', () => choose('source'));
    $('previewModeTarget').addEventListener('click', () => choose('target'));
    $('previewModeCompare').addEventListener('click', () => choose('compare'));
    $('previewModeDiff').addEventListener('click', () => choose('diff'));
    $('previewPrev').addEventListener('click', () => { if (page > 1) { page -= 1; render(); } });
    $('previewNext').addEventListener('click', () => { if (page < availablePages()) { page += 1; render(); } });
    $('previewCanvas').addEventListener('keydown', (event) => {
        if (event.key === 'ArrowLeft' && page > 1) { page -= 1; render(); event.preventDefault(); }
        if (event.key === 'ArrowRight' && page < availablePages()) { page += 1; render(); event.preventDefault(); }
    });

    return {init, open, reset};
}
