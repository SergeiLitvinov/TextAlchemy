"use strict";

const names = {
    'ingest.file': 'Открыть файл',
    'bibliography.parse': 'Прочитать файл библиографии',
    'bibliography.smart_parse': 'Разобрать список литературы',
    'extract.text': 'Извлечь текст',
    'extract.emails': 'Найти адреса электронной почты',
    'extract.html_model': 'Прочитать структуру HTML',
    'extract.epub_model': 'Прочитать электронную книгу',
    'extract.pdf_model': 'Прочитать структуру PDF',
    'extract.pptx_model': 'Прочитать презентацию',
    'match.bibliography': 'Найти источник для документа',
    'match.files': 'Сопоставить файлы с литературой',
    'name.from_match': 'Составить имя файла по источнику',
    'render.emails.docx': 'Сохранить адреса в Word',
    'render.emails.txt': 'Сохранить адреса в текстовый файл',
    'render.emails.debug': 'Сохранить текст распознавания',
    'render.latex': 'Создать статью LaTeX',
    'render.latex.pandoc': 'Создать LaTeX через Pandoc',
    'render.docx': 'Сохранить текст в Word',
    'render.bibtex': 'Экспортировать литературу в BibTeX',
    'render.gost': 'Оформить литературу по ГОСТ',
    'render.markdown': 'Экспортировать литературу в Markdown',
    'render.json': 'Экспортировать литературу в JSON',
    'render.docx_model': 'Сохранить документ в Word',
    'render.pptx_model': 'Создать презентацию',
    'render.txt_model': 'Сохранить документ как текст',
    'render.html.pptx': 'Создать HTML-просмотр презентации',
    'template.render': 'Заполнить шаблон данными',
};
const groups = {ingest: 'Исходные файлы', extract: 'Чтение документов', bibliography: 'Литература',
    match: 'Сопоставление', name: 'Имена файлов', render: 'Создание и экспорт', template: 'Шаблоны', other: 'Другие действия'};
const parameters = {path: 'Путь к файлу', title: 'Заголовок', author: 'Автор', output: 'Файл результата',
    output_path: 'Путь результата', output_dir: 'Папка результата', items: 'Записи литературы', text: 'Текст', data: 'Данные шаблона'};

export const operationLabel = id => names[id] || id;
export const groupLabel = id => groups[id] || id;
export const parameterLabel = id => parameters[id] || id;
