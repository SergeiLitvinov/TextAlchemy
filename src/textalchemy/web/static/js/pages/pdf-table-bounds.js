"use strict";

export function createTableBounds($, changed) {
    const ids = ['tableFirstRow', 'tableLastRow', 'tableFirstColumn', 'tableLastColumn'];
    let block = null, page = null, pending = {};

    function valid(table) {
        const [r0, r1, c0, c1] = table.range;
        return table.range.every(Number.isInteger) && r0 >= 1 && r1 >= r0 && r1 <= table.rows &&
            c0 >= 1 && c1 >= c0 && c1 <= table.columns;
    }

    function preview() {
        $('tablePreview').replaceChildren();
        if (!block?.table) return;
        const table = block.table;
        if (!valid(table)) {
            $('tableMessage').textContent = 'Укажите непустой диапазон в пределах исходной таблицы.';
            return;
        }
        const [r0, r1, c0, c1] = table.range;
        $('tableMessage').textContent = `Результат: ${r1 - r0 + 1} строк, ${c1 - c0 + 1} столбцов. ` +
            'Ячейки за границами не попадут в экспорт. Для отмены выберите всю исходную таблицу.';
        const selectedBoxes = [];
        for (let r = r0 - 1; r < r1; r++) {
            const row = document.createElement('tr');
            for (let c = c0 - 1; c < c1; c++) {
                const cell = document.createElement('td'); cell.textContent = table.cells[r][c]; row.append(cell);
                selectedBoxes.push(table.boxes[r * table.columns + c]);
            }
            $('tablePreview').append(row);
        }
        const x0 = Math.min(...selectedBoxes.map(b => b[0])), y0 = Math.min(...selectedBoxes.map(b => b[1]));
        const x1 = Math.max(...selectedBoxes.map(b => b[2])), y1 = Math.max(...selectedBoxes.map(b => b[3]));
        Object.assign($('orderRegion').style, {left: 100 * x0 / page.width + '%', top: 100 * y0 / page.height + '%',
            width: 100 * (x1 - x0) / page.width + '%', height: 100 * (y1 - y0) / page.height + '%'});
        $('orderRegion').hidden = false;
    }

    function edit() {
        if (!block?.table) return;
        block.table.range = ids.map(id => $(id).value === '' ? NaN : Number($(id).value));
        pending[block.id] = block.table;
        preview(); changed();
    }
    for (const id of ids) $(id).addEventListener('input', edit);
    $('tableReset').onclick = () => {
        if (!block?.table) return;
        const table = block.table;
        table.range = [1, table.rows, 1, table.columns];
        table.range.forEach((n, i) => { $(ids[i]).value = n; }); edit();
    };
    return {
        reset() { pending = {}; },
        select(selected, currentPage) {
            block = selected; page = currentPage;
            $('tableBounds').hidden = !block?.table;
            if (!block?.table) return;
            block.table.range.forEach((n, i) => { $(ids[i]).value = Number.isFinite(n) ? n : ''; });
            ids.forEach((id, i) => { $(id).max = i < 2 ? block.table.rows : block.table.columns; });
            preview();
        },
        disable(busy) { for (const id of [...ids, 'tableReset']) $(id).disabled = busy; },
        changes() {
            if (Object.values(pending).some(table => !valid(table))) throw new Error('Проверьте границы изменённых таблиц.');
            return Object.fromEntries(Object.entries(pending).map(([id, table]) => [id, table.range]));
        },
    };
}
