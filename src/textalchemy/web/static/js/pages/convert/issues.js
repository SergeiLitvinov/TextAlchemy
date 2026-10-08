"use strict";

const featureLabels = {
    'heading-quality-budget': 'Проверка заголовков',
    'import.txt-encoding': 'Кодировка TXT',
    'djvu-text-only': 'Текстовый слой DjVu',
    page_geometry: 'Размеры страниц', sections: 'Разделы', styles: 'Оформление', resources: 'Встроенные ресурсы',
    text: 'Текст', tables: 'Таблицы', images: 'Изображения', formulas: 'Формулы', links: 'Ссылки',
    'emphasis-quality': 'Жирное и курсивное выделение', 'formula-quality': 'Сохранность формул',
    'object-quality': 'Сохранность объектов', 'text-quality': 'Сохранность текста',
    'color-icc': 'Цветовой профиль', 'color-blend': 'Наложение цветов',
    'image-vector': 'Векторное изображение',
    'pdf-vector-surrogate': 'Замена PDF-вектора',
    'pdf-vector-unsupported': 'Неподдержанный PDF-вектор',
    'pdf-vector-style': 'Оформление PDF-вектора',
    'pdf-raster-unsupported': 'Изображение не перенесено в PDF',
    'pdf-raster-compositing': 'Наложение объектов PDF',
    'pdf.annotations': 'Аннотации и ссылки PDF', 'pdf.forms': 'Поля PDF-формы',
    'pdf.annotation': 'Аннотация исходного PDF', 'pdf.form': 'Поле исходного PDF',
    'pdf.outline': 'Оглавление PDF', 'pdf.catalog': 'Структура исходного PDF',
    'html-css': 'Оформление HTML', 'html-resource': 'Ресурсы HTML', 'html-content': 'Содержимое HTML',
    'html-list': 'Список HTML', 'hyperlink': 'Навигация по ссылкам',
};

const featureExplanations = {
    'pdf-raster-unsupported': 'Изображение не удалось безопасно перенести в PDF. Экспорт остановлен, результат не выдан. Подробная причина указана в диагностике обработчика.',
    'pdf-raster-compositing': 'Порядок наложения изображений, текста и векторных объектов может отличаться от исходника. Проверьте участки, где объекты перекрывают друг друга.',
    'pdf.annotations': 'Аннотации и ссылки сохранены в модели как данные, но не создаются в итоговом PDF. Их интерактивное поведение не сохранено.',
    'pdf.forms': 'Поля PDF-формы сохранены в модели как данные, но не создаются в итоговом PDF. Заполнение и действия полей в результате недоступны.',
    'pdf.outline': 'Оглавление исходного PDF сохранено как расширение и исходное вложение. Экспорт модели не восстанавливает оглавление в PDF.',
    'pdf.catalog': 'Часть структуры PDF сохранена только в исходном вложении. Это не означает сохранение структуры в преобразованном документе.',
    'pdf-vector-surrogate': 'Неподдержанный PDF-вектор заменён предоставленным изображением PNG. Отдельные линии и кривые в нём не редактируются. Если замена некорректна, результат отклонён; причину смотрите в диагностике.',
    'pdf-vector-unsupported': 'PDF-вектор не поддерживается, а допустимое изображение для замены не предоставлено. Результат не выдан; прежний файл сохранён.',
    'pdf-vector-style': 'Для PDF-вектора не хватает исходных параметров оформления. Обработчик использовал значения по умолчанию; проверьте вид линий и контуров.',
    'color-icc': 'Цвет преобразован в sRGB; исходный ICC-профиль не применяется. Оттенки при печати могут отличаться.',
    'color-blend': 'Режим наложения цветов не гарантируется в выбранном формате. Перекрывающиеся элементы могут выглядеть иначе.',
    'image-vector': 'SVG заменён изображением PNG для экспорта в PDF. Векторные элементы нельзя редактировать по отдельности.',
};

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
        feature.textContent = featureLabels[issue.feature] || 'Замечание';
        feature.title = issue.feature;
        const message = document.createElement('span');
        message.textContent = issue.feature === 'pdf-vector-surrogate' && issue.severity === 'error'
            ? 'Предоставленное изображение для замены PDF-вектора не прошло проверку. Результат не выдан; причину смотрите в диагностике.'
            : featureExplanations[issue.feature] || issue.message;
        item.append(feature, message);
        if (Object.hasOwn(featureExplanations, issue.feature)) {
            const details = document.createElement('details');
            details.className = 'issue-diagnostic';
            const summary = document.createElement('summary');
            summary.textContent = 'Диагностика обработчика';
            const original = document.createElement('p');
            original.textContent = issue.message;
            details.append(summary, original);
            item.appendChild(details);
        }
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
