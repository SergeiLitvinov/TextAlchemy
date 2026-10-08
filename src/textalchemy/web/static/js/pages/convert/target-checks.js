"use strict";

const labels = {
    text_edit: 'Правка текста', table_cell_edit: 'Правка ячейки', save_reopen: 'Сохранение и повторное открытие',
    heading_outline: 'Уровень заголовка', inline_image: 'Встроенное изображение', bold: 'Жирное выделение',
};

export function renderTargetChecks($, report) {
    const section = $('targetProgramChecks');
    const list = $('targetProgramCheckList');
    list.replaceChildren();
    const records = report.metrics?.target_program_checks || [];
    section.hidden = records.length === 0;
    if (report.success !== false && records.some(record => Object.values(record.checks).some(value => value === false))) {
        $('qualityBadge').className = 'quality-badge warn';
        $('qualityBadge').textContent = 'Есть замечания проверки Word';
    }
    for (const record of records) {
        const item = document.createElement('li');
        const title = document.createElement('strong');
        title.textContent = `${record.program.name} ${record.program.version} · сборка ${record.program.build}`;
        item.append(title);
        const conditions = document.createElement('p');
        conditions.className = 'field-help';
        conditions.textContent = `Автоматизированная проверка Word (COM) · ${new Date(record.checked_at).toLocaleString()}`;
        item.append(conditions);
        const checks = document.createElement('ul');
        checks.className = 'issue-list';
        for (const [key, label] of Object.entries(labels)) {
            const value = record.checks[key];
            const row = document.createElement('li');
            row.className = value === false ? 'target-check-failed' : '';
            row.textContent = `${label}: ${value === true ? 'подтверждено' : value === false ? 'не прошло' : 'не проверено'}.`;
            if (key === 'heading_outline' && record.observations?.heading_outline_level != null) {
                row.textContent += ` Наблюдаемый уровень: ${record.observations.heading_outline_level}.`;
            }
            checks.append(row);
        }
        item.append(checks);
        const diagnostic = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Условия и отпечатки проверенных файлов';
        const data = document.createElement('pre');
        data.className = 'report-json';
        data.textContent = JSON.stringify({scope: record.scope, artifact_sha256: record.artifact_sha256,
            edited_sha256: record.edited_sha256}, null, 2);
        diagnostic.append(summary, data);
        item.append(diagnostic);
        list.append(item);
    }
}
