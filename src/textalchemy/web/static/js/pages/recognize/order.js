"use strict";

// A newline is a paragraph boundary in the OCR draft model, including empty paragraphs.
export function createParagraphOrder($, changed) {
    const text = $('result');
    let enabled = false;
    let movedSelection = null;

    function selection() {
        const lines = text.value.split('\n');
        if (movedSelection && movedSelection.value === text.value &&
            movedSelection.from === text.selectionStart && movedSelection.to === text.selectionEnd) {
            return {lines, start: movedSelection.start, end: movedSelection.end};
        }
        movedSelection = null;
        const start = text.value.slice(0, text.selectionStart).split('\n').length - 1;
        // Selecting up to the start of the next paragraph excludes that paragraph.
        const endOffset = text.selectionEnd < text.value.length && text.selectionEnd > text.selectionStart &&
            text.value[text.selectionEnd - 1] === '\n' ? text.selectionEnd - 1 : text.selectionEnd;
        const end = text.value.slice(0, endOffset).split('\n').length - 1;
        return {lines, start, end};
    }

    function refresh() {
        const {lines, start, end} = selection();
        $('paragraphUp').disabled = !enabled || start === 0;
        $('paragraphDown').disabled = !enabled || end === lines.length - 1;
        $('paragraphPosition').textContent = enabled ?
            `Выбраны абзацы: ${start + 1}–${end + 1} из ${lines.length}` : '';
    }

    function move(direction) {
        const {lines, start, end} = selection();
        if (!enabled || (direction < 0 ? start === 0 : end === lines.length - 1)) return;
        const moved = lines.splice(start, end - start + 1);
        const target = start + direction;
        lines.splice(target, 0, ...moved);
        text.value = lines.join('\n');
        const offset = lines.slice(0, target).reduce((length, line) => length + line.length + 1, 0);
        text.focus();
        const length = moved.join('\n').length + (target + moved.length < lines.length ? 1 : 0);
        text.setSelectionRange(offset, offset + length);
        movedSelection = {value: text.value, from: offset, to: offset + length,
            start: target, end: target + moved.length - 1};
        changed();
        refresh();
    }

    $('paragraphUp').addEventListener('click', () => move(-1));
    $('paragraphDown').addEventListener('click', () => move(1));
    for (const event of ['select', 'click', 'keyup', 'input']) text.addEventListener(event, refresh);
    return {update(value) { enabled = value; refresh(); }};
}
