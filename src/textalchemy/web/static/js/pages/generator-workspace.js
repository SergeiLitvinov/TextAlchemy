"use strict";

export function createGeneratorWorkspace($, onModeChange = () => {}) {
    let editing = false, step = 0, documentView = false;
    const panels = ['documentBasis', 'documentFields', 'documentOutput'];
    const headings = ['document-basis-title', 'data-fields-title', 'document-output-title'];
    const steps = [...document.querySelectorAll('[data-generator-step]')];
    function showDocument(value) {
        documentView = value;
        $('generate-form').dataset.view = value ? 'document' : 'form';
        $('generatorDocumentView').textContent = value ? 'Вернуться к форме' : 'Посмотреть документ';
        $('generatorDocumentView').setAttribute('aria-pressed', String(value));
    }
    function displayStep(focus = false) {
        panels.forEach((id, index) => { $(id).hidden = editing || step !== index; });
        steps.forEach((button, index) => {
            button.toggleAttribute('aria-current', !editing && step === index);
            if (button.hasAttribute('aria-current')) button.setAttribute('aria-current', 'step');
            button.disabled = editing;
        });
        $('generatorStepActions').hidden = editing;
        $('generatorBack').hidden = step === 0;
        $('generatorNext').hidden = step === 2;
        $('generatorNext').textContent = step === 0 ? 'К данным' : 'К скачиванию';
        if (focus) $(headings[step]).focus({preventScroll: true});
    }
    function move(value) {
        if (editing) return;
        if (value > 0 && (!$('template').value || $('genBtn').disabled)) {
            window.toast('Дождитесь загрузки шаблона и данных.', 'info'); return;
        }
        step = value;
        showDocument(false);
        displayStep(true);
    }
    function show(edit) {
        editing = edit;
        showDocument(false);
        $('generate-form').dataset.mode = edit ? 'edit' : 'fill';
        $('templateEditor').hidden = !edit;
        displayStep();
        for (const [id, active] of [['fillMode', !edit], ['editMode', edit]]) {
            $(id).classList.toggle('active', active);
            $(id).setAttribute('aria-pressed', String(active));
        }
        onModeChange(edit);
    }
    $('fillMode').onclick = () => show(false);
    $('editMode').onclick = () => show(true);
    $('generatorBack').onclick = () => move(step - 1);
    $('generatorNext').onclick = () => move(step + 1);
    $('generatorDocumentView').onclick = () => {
        showDocument(!documentView);
        $(documentView ? 'preview-title' : editing ? 'template-editor-title' : headings[step]).focus({preventScroll: true});
    };
    steps.forEach(button => { button.onclick = () => move(Number(button.dataset.generatorStep)); });
    displayStep();
    return {
        isEditing: () => editing,
        showFields() { step = 1; show(false); displayStep(true); },
        finish() {
            step = 1; show(false); displayStep(true);
            window.toast('Копия шаблона сохранена. Заполните данные нового документа.', 'success');
        },
    };
}
