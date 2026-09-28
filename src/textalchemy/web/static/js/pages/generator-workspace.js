"use strict";

export function createGeneratorWorkspace($) {
    let editing = false;
    function show(edit) {
        editing = edit;
        $('templateEditor').hidden = !edit;
        $('documentFields').hidden = edit;
        $('documentOutput').hidden = edit;
        for (const [id, active] of [['fillMode', !edit], ['editMode', edit]]) {
            $(id).classList.toggle('active', active);
            $(id).setAttribute('aria-pressed', String(active));
        }
    }
    $('fillMode').onclick = () => show(false);
    $('editMode').onclick = () => show(true);
    return {
        isEditing: () => editing,
        finish() {
            show(false);
            $('data-fields-title').focus();
            window.toast('Копия шаблона сохранена. Заполните данные нового документа.', 'success');
        },
    };
}
