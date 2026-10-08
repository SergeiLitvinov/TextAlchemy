"use strict";

export function createExperienceController($, changed) {
    let expert = false;
    function set(value) {
        expert = value;
        $('conversionWorkspace').dataset.experience = expert ? 'expert' : 'simple';
        $('simpleConversionBtn').setAttribute('aria-pressed', String(!expert));
        $('expertConversionBtn').setAttribute('aria-pressed', String(expert));
        if (!expert) {
            for (const id of ['maxLossIssues', 'maxLostObjects', 'maxChangedFormulas', 'maxChangedEmphasis', 'maxChangedHeadings', 'textPreservation']) $(id).value = '';
            $('txtEncoding').value = 'auto';
            $('minRetention').value = '0';
            $('maxTextEdits').value = '0';
            $('maxTextEdits').disabled = true;
            $('textEditBudget').hidden = true;
            $('mode').value = 'balanced';
            $('batchIndividualOptions').open = false;
            document.querySelector('.conversion-loss-budget').open = false;
        }
        $('experienceHelp').textContent = expert
            ? 'Выберите приоритет и строгие допуски. Возврат в простой режим сбросит эти настройки и индивидуальные настройки пакета.'
            : 'Автоматический маршрут и отчёт о качестве. Расширенные проверки и настройки пакета сброшены.';
        changed(!expert);
    }
    $('simpleConversionBtn').addEventListener('click', () => set(false));
    $('expertConversionBtn').addEventListener('click', () => set(true));
    return {
        expert: () => expert,
        stage(index) {
            document.querySelectorAll('.conversion-workflow > li').forEach((step, position) => {
                step.classList.toggle('active', position === index);
                if (position === index) step.setAttribute('aria-current', 'step');
                else step.removeAttribute('aria-current');
            });
        },
        batchRequired(value) { $('simpleConversionBtn').disabled = value; },
        enableForBatch() {
            $('simpleConversionBtn').disabled = true;
            set(true);
            $('batchIndividualOptions').open = true;
            $('experienceHelp').textContent = 'Для этих файлов нет общего формата. Проверьте формат каждого файла в индивидуальных настройках ниже.';
        },
    };
}
