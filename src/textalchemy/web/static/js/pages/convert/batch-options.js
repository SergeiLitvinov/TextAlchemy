"use strict";

const modeLabels = {balanced: 'Разумный баланс', faithful: 'Максимально похожий вид', editable: 'Можно редактировать'};

export function createBatchOptions($) {
    let rows = [];

    function modes(row, preferred) {
        const target = row.source.targets.find((item) => item.format === row.target.value);
        row.mode.replaceChildren(...target.modes.map((mode) => new Option(modeLabels[mode] || mode, mode)));
        row.mode.value = target.modes.includes(preferred) ? preferred : target.modes[0];
        row.help.textContent = (target.guidance || []).join(' ');
    }

    function defaults(target, mode, force = false) {
        for (const row of rows) {
            if (row.changed && !force) continue;
            row.target.value = row.source.targets.some((item) => item.format === target)
                ? target : row.source.default_target || row.source.targets[0].format;
            modes(row, mode);
            row.changed = false;
        }
    }

    $('batchApplyDefaults').addEventListener('click', () => defaults($('target').value, $('mode').value, true));
    return {
        defaults,
        mount(files, sources) {
            rows = [];
            $('batchOptionsList').replaceChildren();
            files.forEach((file, index) => {
                const fieldset = document.createElement('fieldset');
                const legend = document.createElement('legend');
                legend.textContent = `${index + 1}. ${file.name}`;
                fieldset.append(legend);
                const target = document.createElement('select');
                const mode = document.createElement('select');
                for (const [select, name, prefix] of [[target, 'Формат результата', 'batchTarget'], [mode, 'Приоритет', 'batchMode']]) {
                    select.id = `${prefix}${index}`;
                    const label = document.createElement('label');
                    label.htmlFor = select.id;
                    label.textContent = name;
                    fieldset.append(label, select);
                }
                target.replaceChildren(...sources[index].targets.map((item) => new Option(item.label, item.format)));
                const help = document.createElement('p');
                help.className = 'field-help';
                fieldset.append(help);
                const row = {source: sources[index], target, mode, help, changed: false};
                target.addEventListener('change', () => { row.changed = true; modes(row, mode.value); });
                mode.addEventListener('change', () => { row.changed = true; });
                rows.push(row);
                $('batchOptionsList').append(fieldset);
            });
            defaults($('target').value, $('mode').value);
        },
        values() { return rows.map((row) => ({target_format: row.target.value, mode: row.mode.value})); },
    };
}
