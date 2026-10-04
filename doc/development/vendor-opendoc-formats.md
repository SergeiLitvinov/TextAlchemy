# Зависимость OpenDoc Formats

Неизменённый wheel [официального выпуска v0.3.0](https://github.com/SergeiLitvinov/opendoc-formats/releases/tag/v0.3.0).
Обработчики, экспортёры, LaTeX, OOXML/шрифты, PDF-растры, офисный предпросмотр, нативные правки DOCX и ресурсы CSS/JS/Lua принадлежат библиотеке.
В приложении только совместимые импорты и управление маршрутами. Соседний checkout не нужен.
Содержимое закреплено хешами provenance.json и lockfile; установленный код и CSS/JS/Lua проверяются
`uv run python -m tools.check_library_contracts`. Обновление — через `tools.update_format_adapters`
с опубликованным SHA-256, URL выпуска и commit. Пересборка библиотек в сессии приложения запрещена.
Не редактируйте установленную библиотеку вручную.
