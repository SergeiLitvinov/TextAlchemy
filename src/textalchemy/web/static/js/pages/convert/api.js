"use strict";

export const conversionApi = {
    capabilities: () => window.api('/api/convert/capabilities'),
    inspect(file) {
        const formData = new FormData();
        formData.set('file', file);
        return window.api('/api/convert/inspect', {method: 'POST', formData});
    },
    start(file, targetFormat, mode, minRetention, maxLossIssues = '', maxLostObjects = '', requireUnchangedText = false, textPreservation = '', maxTextEdits = '', maxChangedFormulas = '', maxChangedEmphasis = '', maxChangedHeadings = '', txtEncoding = 'auto') {
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
        if (maxChangedEmphasis !== '' && maxChangedEmphasis != null) formData.set('max_changed_emphasis', maxChangedEmphasis);
        formData.set('txt_encoding', txtEncoding);
        if (maxChangedHeadings !== '' && maxChangedHeadings != null) formData.set('max_changed_headings', maxChangedHeadings);
        if (maxChangedFormulas !== '' && maxChangedFormulas != null) formData.set('max_changed_formulas', maxChangedFormulas);
        return window.api('/api/convert', {method: 'POST', formData});
    },
    startBatch(files, targetFormat, mode, minRetention, maxLossIssues = '', maxLostObjects = '', requireUnchangedText = false, textPreservation = '', maxTextEdits = '', fileOptions = null, maxChangedFormulas = '', maxChangedEmphasis = '', maxChangedHeadings = '', txtEncoding = 'auto') {
        const formData = new FormData();
        for (const file of files) formData.append('files', file);
        if (fileOptions) formData.set('file_options', JSON.stringify(fileOptions));
        formData.set('target_format', targetFormat);
        formData.set('mode', mode);
        formData.set('min_retention', minRetention);
        if (maxLossIssues !== '' && maxLossIssues != null) formData.set('max_loss_issues', maxLossIssues);
        if (maxLostObjects !== '' && maxLostObjects != null) formData.set('max_lost_objects', maxLostObjects);
        formData.set('require_unchanged_text', String(requireUnchangedText));
        if (textPreservation) formData.set('text_preservation', textPreservation);
        if (maxTextEdits !== '' && maxTextEdits != null) formData.set('max_text_edits', maxTextEdits);
        if (maxChangedEmphasis !== '' && maxChangedEmphasis != null) formData.set('max_changed_emphasis', maxChangedEmphasis);
        formData.set('txt_encoding', txtEncoding);
        if (maxChangedHeadings !== '' && maxChangedHeadings != null) formData.set('max_changed_headings', maxChangedHeadings);
        if (maxChangedFormulas !== '' && maxChangedFormulas != null) formData.set('max_changed_formulas', maxChangedFormulas);
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
    rerunJob(jobId, failedOnly = false, taskIds = null) {
        const formData = new FormData();
        formData.set('failed_only', String(failedOnly));
        if (taskIds !== null) formData.set('task_ids', JSON.stringify(taskIds));
        return window.api('/api/convert/jobs/' + encodeURIComponent(jobId) + '/rerun', {method: 'POST', formData});
    },
    deleteJob(jobId) {
        return window.api('/api/convert/jobs/' + encodeURIComponent(jobId), {method: 'DELETE'});
    },
    cancelJob(jobId, taskIds = null) {
        const formData = new FormData();
        if (taskIds !== null) formData.set('task_ids', JSON.stringify(taskIds));
        return window.api('/api/convert/jobs/' + encodeURIComponent(jobId) + '/cancel', {method: 'POST', formData});
    },
    previewMeta(taskId) {
        return window.api(`/api/convert/preview/${encodeURIComponent(taskId)}/meta`);
    },
    async previewPage(taskId, side, page, dpi = 110) {
        const url = `/api/convert/preview/${encodeURIComponent(taskId)}?side=${side}&page=${page}&dpi=${dpi}`;
        const response = await fetch(url, {cache: 'no-cache'});
        if (!response.ok) throw new Error('preview fetch failed');
        return response.blob();
    },
    async previewDiff(taskId, page, dpi = 110) {
        const response = await fetch(`/api/convert/preview/${encodeURIComponent(taskId)}/diff?page=${page}&dpi=${dpi}`, {cache: 'no-cache'});
        if (!response.ok) throw new Error('preview diff fetch failed');
        const header = response.headers.get('X-Visual-Similarity');
        const value = header?.trim() ? Number(header) : null;
        return {
            blob: await response.blob(),
            similarity: Number.isFinite(value) && value >= 0 && value <= 1 ? value : null,
        };
    },
};

export async function downloadResult(url, filename) {
    const response = await fetch(url);
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        window.toast(typeof error.detail === 'string' ? error.detail : 'Результат пока недоступен', 'error');
        return;
    }
    const blob = await response.blob();
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = filename || 'converted';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
}
