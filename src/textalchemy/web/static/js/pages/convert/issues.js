"use strict";

export function renderIssues($, report) {
    const issues = report.issues || [];
    const locations = report.metrics?.step_metrics?.['html.model']?.html_locations || {};
    const list = $('issueList');
    const inspector = $('issueInspector');
    list.replaceChildren();
    inspector.hidden = true;
    $('issueFragment').replaceChildren();
    $('issuesSection').hidden = !issues.length;
    for (const issue of issues) {
        const item = document.createElement('li');
        item.className = `issue-${['info', 'warning', 'loss', 'error'].includes(issue.severity) ? issue.severity : 'info'}`;
        const feature = document.createElement('strong');
        feature.textContent = issue.feature;
        const message = document.createElement('span');
        message.textContent = issue.message;
        item.append(feature, message);
        const target = Object.hasOwn(locations, issue.location) ? locations[issue.location] : null;
        if (target) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn-secondary';
            button.textContent = issue.location === 'html:document' ? 'Весь документ' : `Показать фрагмент: ${target.label}`;
            button.setAttribute('aria-controls', 'issueInspector');
            button.setAttribute('aria-pressed', 'false');
            button.addEventListener('click', () => {
                for (const other of list.querySelectorAll('button')) other.setAttribute('aria-pressed', 'false');
                button.setAttribute('aria-pressed', 'true');
                $('issueLocationTitle').textContent = target.label;
                const fragment = $('issueFragment');
                fragment.replaceChildren();
                const text = document.createElement('p');
                text.textContent = target.text || 'В этом блоке нет текста.';
                fragment.appendChild(text);
                for (const image of target.images || []) {
                    const description = document.createElement('p');
                    description.textContent = `Изображение: ${image.alt || 'без подписи'}${image.source ? ` — ${image.source}` : ''}`;
                    fragment.appendChild(description);
                }
                inspector.dataset.location = issue.location;
                inspector.hidden = false;
                inspector.focus({preventScroll: true});
                inspector.scrollIntoView({behavior: 'smooth', block: 'center'});
            });
            item.appendChild(button);
        } else if (issue.location) {
            const location = document.createElement('small');
            location.textContent = issue.location;
            item.appendChild(location);
        }
        list.appendChild(item);
    }
}
