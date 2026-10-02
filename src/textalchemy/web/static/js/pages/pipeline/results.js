"use strict";
const {operationLabel} = await import('./labels.js' + new URL(import.meta.url).search);

export function renderPipelineResult($, response) {
    const result = response.result;
    const success = response.success === true && result?.ok === true;
    const steps = result?.steps || [];
    $('pipeline-result').hidden = false;
    $('pipeline-result-title').textContent = success ? 'Сценарий выполнен' : 'Сценарий не выполнен';
    $('resultSummary').textContent = success
        ? `Завершено шагов: ${steps.length}. Ниже результат последнего запуска.`
        : (result?.error || response.error || 'Не удалось выполнить сценарий. Проверьте шаги и повторите запуск.');
    $('resultSteps').replaceChildren(...steps.map((step, index) => {
        const item = document.createElement('li');
        const title = document.createElement('strong');
        title.textContent = `${index + 1}. ${operationLabel(step.op)} — ${step.error ? 'ошибка' : 'выполнено'}`;
        item.append(title);
        for (const message of [step.error, ...(step.warnings || [])].filter(Boolean)) {
            const note = document.createElement('p'); note.textContent = message; item.append(note);
        }
        return item;
    }));
    const value = result?.final;
    const scalar = value !== null && value !== undefined && typeof value !== 'object';
    $('resultValue').hidden = !success || !scalar;
    $('resultValue').textContent = scalar ? String(value) : '';
    $('resultValueNote').textContent = !success ? 'Исправьте причину ошибки перед повторным запуском.'
        : scalar ? 'Текст результата или путь к созданному файлу на компьютере, где запущено приложение.'
        : value == null ? 'Сценарий завершён без итогового значения.' : 'Получены структурированные данные. Они доступны в подробном отчёте.';
    $('result-output').textContent = JSON.stringify(response, null, 2);
    $('resultDownloads').replaceChildren(...(response.downloads || []).map(file => {
        const link = document.createElement('a'); link.href = file.url; link.download = file.name;
        link.textContent = `Скачать ${file.name}`; return link;
    }));
    if (response.downloads?.length) $('resultValueNote').textContent = 'Файлы результата доступны для скачивания в течение часа.';
    $('pipeline-result-title').focus();
    return success;
}
