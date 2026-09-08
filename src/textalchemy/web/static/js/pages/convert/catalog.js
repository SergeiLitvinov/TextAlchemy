"use strict";

const modeLabels = {
    balanced: 'Разумный баланс', faithful: 'Максимально похожий вид', editable: 'Можно редактировать',
};

export function renderCatalog(container, capabilities) {
    container.replaceChildren();
    const sources = [...capabilities.sources, ...(capabilities.unavailable_sources || [])];
    if (!sources.length) {
        container.textContent = 'В текущей установке нет доступных направлений конвертации.';
        return;
    }
    for (const source of sources) {
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = `${source.label} — ${source.targets.map((target) => target.label).join(', ') || 'нет доступных направлений'}`;
        details.append(summary);
        const list = document.createElement('ul');
        for (const target of source.targets) {
            const item = document.createElement('li');
            item.textContent = `${target.label}: ${target.modes.map((mode) => modeLabels[mode] || mode).join(', ')}.`;
            appendReasons(item, target);
            for (const note of target.guidance || []) {
                const paragraph = document.createElement('p');
                paragraph.className = 'field-help';
                paragraph.textContent = note;
                item.append(paragraph);
            }
            list.append(item);
        }
        details.append(list);
        if (source.unavailable_targets?.length) {
            const blocked = document.createElement('details');
            const title = document.createElement('summary');
            title.textContent = 'Почему другие форматы недоступны';
            blocked.append(title);
            for (const target of source.unavailable_targets) {
                const section = document.createElement('div');
                const heading = document.createElement('strong');
                heading.textContent = target.label;
                section.append(heading);
                appendReasons(section, target);
                blocked.append(section);
            }
            details.append(blocked);
        }
        container.append(details);
    }
}

function appendReasons(container, target) {
    for (const [mode, reason] of Object.entries(target.unavailable_modes || {})) {
        const paragraph = document.createElement('p');
        paragraph.className = 'field-help';
        paragraph.textContent = `${modeLabels[mode] || mode}: ${reason.message}`;
        container.append(paragraph);
    }
}

export function unavailableModeHelp(sources, targetFormat, modes) {
    const messages = new Set();
    for (const source of sources) {
        const target = source.targets.find((item) => item.format === targetFormat);
        for (const mode of modes) {
            const reason = target?.unavailable_modes?.[mode];
            if (reason) messages.add(`${source.label}: ${modeLabels[mode] || mode} — ${reason.message}`);
        }
    }
    return Array.from(messages).join(' ');
}

export function renderGuidance(list, sources, targetFormat) {
    const notes = new Set(sources.flatMap((source) =>
        source.targets.find((target) => target.format === targetFormat)?.guidance || []));
    list.replaceChildren();
    for (const note of notes) {
        const item = document.createElement('li');
        item.textContent = note;
        list.append(item);
    }
    return notes.size > 0;
}
