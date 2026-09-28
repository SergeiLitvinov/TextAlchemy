"use strict";

export function createPdfDiagnostics($, navigate) {
    function clear() { $('pdfDiagnostics').hidden = true; $('pdfIssueList').replaceChildren(); }
    function render(report) {
        clear(); $('pdfDiagnostics').hidden = false;
        $('pdfIssueSummary').textContent = report.issues.length ?
            `Замечаний при пробном экспорте DOCX: ${report.issues.length}. Проверена версия ${report.revision}.` :
            `Версия ${report.revision}: экспортёр не сообщил о проблемах. Это не полная проверка сохранности.`;
        for (const issue of report.issues) {
            const row = document.createElement('li');
            const message = document.createElement('p'); message.textContent = `${issue.feature}: ${issue.message}`;
            row.append(message);
            if (issue.target) {
                const button = document.createElement('button'); button.type = 'button';
                button.className = 'btn-secondary'; button.setAttribute('aria-controls', 'orderBlocks');
                button.textContent = `Показать блок на странице ${issue.target.page + 1}: ${issue.target.label}`;
                button.onclick = () => navigate(issue.target, issue.message);
                row.append(button);
            } else {
                const note = document.createElement('small');
                note.textContent = 'Нет однозначной ссылки на блок.'; row.append(note);
            }
            $('pdfIssueList').append(row);
        }
    }
    return {clear, render};
}
