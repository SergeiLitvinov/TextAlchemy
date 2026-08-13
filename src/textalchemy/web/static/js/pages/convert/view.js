"use strict";

const stateLabels = {
    queued: 'В очереди…', running: 'Конвертация…', done: 'Готово',
    error: 'Ошибка', interrupted: 'Прервана', expired: 'Истёк срок',
};

export function createConversionView($) {
    function status(message, type = 'info') {
        const element = $('status');
        element.hidden = !message;
        element.className = `status-bar ${type}`;
        element.textContent = message || '';
    }

    function progress(visible, percent, message) {
        $('progressWrap').hidden = !visible;
        $('progressBar').style.width = `${percent}%`;
        $('progressText').textContent = message;
    }

    function inspection(data) {
        const metrics = data?.metrics || {};
        const entries = [
            ['Страницы', metrics.pages], ['Абзацы', metrics.paragraphs],
            ['Таблицы', metrics.tables], ['Изображения', metrics.images], ['Формулы', metrics.formulas],
        ].filter((entry) => entry[1] !== undefined);
        $('inspectionState').textContent = data?.valid ? 'Структура читается' : 'Есть ошибки структуры';
        $('inspectionMetrics').innerHTML = entries.map(([label, value]) =>
            `<div><span>${window.esc(label)}</span><strong>${window.esc(value)}</strong></div>`
        ).join('');
        const issues = data?.issues || [];
        $('inspectionMessage').textContent = issues.length
            ? `Найдено замечаний: ${issues.length}. Они будут учтены в итоговом отчёте.`
            : 'Критичных структурных проблем не найдено.';
    }

    function batchProgress(tasks) {
        $('batchProgressList').innerHTML = tasks.map((task) => {
            const label = stateLabels[task.status] || task.status;
            const download = task.status === 'done' && task.result_url
                ? `<button type="button" class="btn-link" data-download-url="${window.esc(task.result_url)}" data-filename="${window.esc(task.filename || task.name)}">Скачать</button>` : '';
            const preview = task.status === 'done'
                ? `<button type="button" class="btn-link" data-preview-task="${window.esc(task.task_id)}">Просмотр</button>` : '';
            const error = ['error', 'interrupted'].includes(task.status) && task.error
                ? `<small>${window.esc(task.error)}</small>` : '';
            return `<li class="batch-progress-item ${window.esc(task.status)}"><span class="file-name">${window.esc(task.name)}</span>` +
                `<span class="job-state ${window.esc(task.status)}">${window.esc(label)}</span>${download}${preview}${error}</li>`;
        }).join('');
    }

    function comparison(comparisonData, inspectionError) {
        const retention = comparisonData?.retention || {};
        const names = {characters: 'Текст', paragraphs: 'Абзацы', tables: 'Таблицы', images: 'Изображения', formulas: 'Формулы', pages: 'Страницы'};
        const entries = Object.entries(names).filter(([name]) => retention[name]).map(([name, label]) => [label, retention[name]]);
        $('comparisonSection').hidden = entries.length === 0 && !inspectionError;
        $('retentionGrid').innerHTML = entries.map(([label, values]) => {
            const percent = Math.round((values.ratio || 0) * 100);
            const level = percent >= 99 ? 'good' : percent >= 80 ? 'warn' : 'bad';
            return `<div class="retention-item ${level}"><span>${window.esc(label)}</span><strong>${percent}%</strong>` +
                `<small>${window.esc(values.target)} из ${window.esc(values.source)}</small></div>`;
        }).join('');
        $('comparisonMessage').textContent = inspectionError || (comparisonData?.has_losses
            ? 'Обнаружены структурные отличия — подробности перечислены в замечаниях.'
            : 'Проверенные элементы структуры сохранены.');
        const objectDiff = comparisonData?.object_diff;
        const hasObjectData = Boolean(objectDiff?.source_count || objectDiff?.target_count);
        $('objectDiff').hidden = !hasObjectData;
        if (hasObjectData) {
            const metrics = [
                ['Сохранено', objectDiff.retained?.length || 0, 'good'],
                ['Изменено', objectDiff.changed?.length || 0, objectDiff.changed?.length ? 'warn' : 'good'],
                ['Потеряно', objectDiff.lost?.length || 0, objectDiff.lost?.length ? 'bad' : 'good'],
                ['Добавлено', objectDiff.added?.length || 0, 'warn'],
            ];
            $('objectDiffMetrics').innerHTML = metrics.map(([label, value, level]) =>
                `<div class="retention-item ${level}"><span>${label}</span><strong>${value}</strong></div>`
            ).join('');
            const recommendations = objectDiff.recommendations || [];
            $('objectDiffList').innerHTML = recommendations.map((item) => {
                const locations = (item.locations || []).filter(Boolean).slice(0, 5).join(', ');
                return `<li class="issue-warning"><strong>${window.esc(item.message)}</strong>` +
                    `<span>${window.esc(locations || 'Проверьте отмеченные элементы')}</span></li>`;
            }).join('');
        }
    }

    return {status, progress, inspection, batchProgress, comparison};
}
