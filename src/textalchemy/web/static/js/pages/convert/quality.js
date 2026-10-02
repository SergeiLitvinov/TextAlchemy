"use strict";

export function renderQualityGate($, report) {
    const gate = report.metrics?.quality_gate;
    const summary = $('qualityGateSummary');
    summary.hidden = false;
    const setMessage = (key, fallback, values = {}) => {
        summary.dataset.i18n = key;
        summary.dataset.i18nParams = JSON.stringify(values);
        summary.textContent = window.translate?.(key, fallback, values) || fallback;
    };
    if (!gate) {
        setMessage('quality.unchecked', 'Бюджет потерь не проверялся. Отсутствие сообщений не гарантирует полную сохранность.');
        return;
    }
    const values = {count: gate.loss_issues, limit: gate.max_loss_issues};
    const detail = `Сообщений о потерях: ${values.count}; допустимо: ${values.limit}.`;
    if (gate.accepted === false) {
        $('qualityBadge').textContent = window.translate?.('quality.blocked', 'Превышен бюджет потерь') || 'Превышен бюджет потерь';
        setMessage('quality.rejected', `${detail} Результат не выдан. Исходник сохранён для повторного запуска.`, values);
    } else {
        setMessage('quality.accepted', `${detail} Бюджет соблюдён; визуальное сходство и редактируемость этой проверкой не измеряются.`, values);
    }
}

export function renderObjectGate($, report) {
    const gate = report.metrics?.object_quality_gate;
    const summary = $('objectGateSummary');
    summary.hidden = !gate;
    if (!gate) return;
    const values = {count: gate.lost_objects, limit: gate.max_lost_objects};
    let key = 'objects.accepted';
    let message = `Объектов без совпадения: ${values.count}; допустимо: ${values.limit}. Бюджет объектов соблюдён.`;
    if (!gate.accepted) {
        key = gate.verified ? 'objects.rejected' : 'objects.unverified';
        message = gate.verified
            ? `Объектов без совпадения: ${values.count}; допустимо: ${values.limit}. Результат не выдан.`
            : 'Бюджет объектов не удалось проверить: данные неполные или сопоставление неоднозначно. Результат не выдан.';
        $('qualityBadge').textContent = gate.verified ? 'Превышен бюджет объектов' : 'Объекты не проверены';
    }
    summary.dataset.i18n = key;
    summary.dataset.i18nParams = JSON.stringify(values);
    summary.textContent = window.translate?.(key, message, values) || message;
}

export function renderTextGate($, report) {
    const gate = report.metrics?.text_quality_gate;
    const summary = $('textGateSummary');
    summary.hidden = !gate;
    if (!gate) return;
    if (gate.basis === 'word_levenshtein_v1') {
        renderTextEdits($, gate, summary);
        return;
    }
    const flow = gate.mode === 'flow';
    const prefix = flow ? 'textflow' : 'textcheck';
    const key = gate.accepted ? `${prefix}.accepted` : gate.verified ? `${prefix}.rejected` : `${prefix}.unavailable`;
    const values = {count: gate.unmatched_source_paragraphs};
    let message = gate.accepted ? 'Текст исходных абзацев сохранён дословно.' : gate.verified
        ? `Не совпал текст исходных абзацев: ${values.count}. Результат не выдан.`
        : 'Дословную сохранность текста не удалось проверить. Результат не выдан.';
    if (flow) message = gate.accepted ? 'Последовательность текста сохранена с учётом нормализации пробелов и границ абзацев.'
        : gate.verified ? 'Последовательность текста изменилась. Результат не выдан.'
            : 'Последовательность текста не удалось проверить. Результат не выдан.';
    summary.dataset.i18n = key;
    summary.dataset.i18nParams = JSON.stringify(values);
    summary.textContent = window.translate?.(key, message, values) || message;
    if (!gate.accepted) $('qualityBadge').textContent = gate.verified ? 'Текст изменён' : 'Текст не проверен';
}

function renderTextEdits($, gate, summary) {
    const values = {count: gate.text_edits ?? gate.text_edits_lower_bound, limit: gate.max_text_edits};
    const key = gate.accepted ? (gate.text_edits === 0 ? 'textedits.unchanged' : 'textedits.accepted')
        : gate.verified ? 'textedits.rejected' : 'textedits.unavailable';
    const message = gate.accepted
        ? `${gate.text_edits === 0 ? 'Последовательность текста сохранена.' : 'Допуск правок соблюдён.'} Правок слов: ${values.count}; допустимо: ${values.limit}.`
        : gate.verified ? `Правок слов не менее ${values.count}; допустимо: ${values.limit}. Результат не выдан.`
            : 'Число правок текста не удалось проверить: нет данных или превышен лимит вычислений. Результат не выдан.';
    summary.dataset.i18n = key;
    summary.dataset.i18nParams = JSON.stringify(values);
    summary.textContent = window.translate?.(key, message, values) || message;
    if (!gate.accepted) $('qualityBadge').textContent = gate.verified ? 'Превышен допуск правок' : 'Текст не проверен';
    else if (gate.text_edits > 0) {
        $('qualityBadge').className = 'quality-badge warn';
        $('qualityBadge').textContent = `Правок слов: ${gate.text_edits}`;
    }
}

export function renderFormulaGate($, report) {
    const gate = report.metrics?.formula_quality_gate;
    const summary = $('formulaGateSummary'); summary.hidden = !gate;
    if (!gate) return;
    summary.textContent = gate.verified
        ? `Несовпавших или удалённых формул: ${gate.changed_formulas}; допустимо: ${gate.max_changed_formulas}. ` +
            (gate.accepted ? 'Допуск соблюдён.' : 'Результат не выдан.')
        : 'Сохранность формул не удалось проверить. Результат не выдан.';
    if (!gate.accepted) $('qualityBadge').textContent = gate.verified ? 'Превышен допуск формул' : 'Формулы не проверены';
}

export function renderEmphasisGate($, report) {
    const gate = report.metrics?.emphasis_quality_gate;
    const summary = $('emphasisGateSummary'); summary.hidden = !gate;
    if (!gate) return;
    summary.textContent = gate.verified
        ? `Символов с изменённым выделением: ${gate.changed_characters}; допустимо: ${gate.max_changed_emphasis}. ` +
            (gate.accepted ? 'Допуск соблюдён.' : 'Результат не выдан.')
        : 'Выделение не проверено: текст не сопоставим или представление недоступно. Результат не выдан.';
    if (!gate.accepted) $('qualityBadge').textContent = gate.verified ? 'Превышен допуск выделения' : 'Выделение не проверено';
}
