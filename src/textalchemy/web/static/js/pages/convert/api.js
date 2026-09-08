"use strict";

export const conversionApi = {
    capabilities: () => window.api('/api/convert/capabilities'),
    inspect(file) {
        const formData = new FormData();
        formData.set('file', file);
        return window.api('/api/convert/inspect', {method: 'POST', formData});
    },
    start(file, targetFormat, mode, minRetention, maxLossIssues = '', maxLostObjects = '', requireUnchangedText = false, textPreservation = '', maxTextEdits = '') {
        const formData = new FormData();
        formData.set('file', file);
        formData.set('source_format', 'auto');
        formData.set('target_format', targetFormat);
        formData.set('mode', mode);
        formData.set('min_retention', minRetention);
        if (maxLossIssues !== '' && maxLossIssues != null) formData.set('max_loss_issues', maxLossIssues);
        if (maxLostObjects !== '' && maxLostObjects != null) formData.set('max_lost_objects', maxLostObjects);
        formData.set('require_unchanged_text', String(requireUnchangedText));
        if (textPreservation) formData.set('text_preservation', textPreservation);
        if (maxTextEdits !== '' && maxTextEdits != null) formData.set('max_text_edits', maxTextEdits);
        return window.api('/api/convert', {method: 'POST', formData});
    },
    startBatch(files, targetFormat, mode, minRetention, maxLossIssues = '', maxLostObjects = '', requireUnchangedText = false, textPreservation = '', maxTextEdits = '') {
        const formData = new FormData();
        for (const file of files) formData.append('files', file);
        formData.set('target_format', targetFormat);
        formData.set('mode', mode);
        formData.set('min_retention', minRetention);
        if (maxLossIssues !== '' && maxLossIssues != null) formData.set('max_loss_issues', maxLossIssues);
        if (maxLostObjects !== '' && maxLostObjects != null) formData.set('max_lost_objects', maxLostObjects);
        formData.set('require_unchanged_text', String(requireUnchangedText));
        if (textPreservation) formData.set('text_preservation', textPreservation);
        if (maxTextEdits !== '' && maxTextEdits != null) formData.set('max_text_edits', maxTextEdits);
        return window.api('/api/convert/batch', {method: 'POST', formData});
    },
    taskStatus(url) {
        return window.api(url);
    },
    task(taskId) {
        return window.api('/api/convert/status/' + encodeURIComponent(taskId));
    },
    jobs() {
        return window.api('/api/convert/jobs');
    },
    job(jobId) {
        return window.api('/api/convert/jobs/' + encodeURIComponent(jobId));
    },
    rerunJob(jobId) {
        return window.api('/api/convert/jobs/' + encodeURIComponent(jobId) + '/rerun', {method: 'POST'});
    },
    deleteJob(jobId) {
        return window.api('/api/convert/jobs/' + encodeURIComponent(jobId), {method: 'DELETE'});
    },
    previewMeta(taskId) {
        return window.api(`/api/convert/preview/${encodeURIComponent(taskId)}/meta`);
    },
    async previewPage(taskId, side, page, dpi = 110) {
        const url = `/api/convert/preview/${encodeURIComponent(taskId)}?side=${side}&page=${page}&dpi=${dpi}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error('preview fetch failed');
        return response.blob();
    },
    async previewDiff(taskId, page, dpi = 110) {
        const response = await fetch(`/api/convert/preview/${encodeURIComponent(taskId)}/diff?page=${page}&dpi=${dpi}`);
        if (!response.ok) throw new Error('preview diff fetch failed');
        return {
            blob: await response.blob(),
            similarity: Number(response.headers.get('X-Visual-Similarity')),
        };
    },
};

export async function downloadResult(url, filename) {
    const response = await fetch(url);
    if (!response.ok) {
        window.toast('Результат пока недоступен', 'error');
        return;
    }
    const blob = await response.blob();
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = filename || 'converted';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
}
