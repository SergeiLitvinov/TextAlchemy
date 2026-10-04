# Зависимость OpenDoc

Здесь хранится неизменённый официальный wheel [OpenDoc v0.1.0](https://github.com/SergeiLitvinov/opendoc/releases/tag/v0.1.0), без её исходного проекта. Он позволяет установить TextAlchemy и запустить CI без каталога `C:/project/opendoc`.

`provenance.json` фиксирует версию, URL wheel, commit выпуска, проверку опубликованного SHA-256 и хеш каждого Python-модуля. Тест интеграции проверяет их соответствие установленной библиотеке. Сохранённый wheel совпадает с файлом GitHub Releases: `1e1e70905bbe0d75706325fefbb24281c55784be8b1e53ce39f6bb2b2d6068f1`. Исходники OpenDoc не исправлялись и не пересобирались для комплекта.

Получение проверенного пакета: `uv run python -m tools.update_document_core --wheel путь/к/opendoc-0.1.0-py3-none-any.whl`, затем `uv sync --all-extras --reinstall-package opendoc` и проверки приложения. Инструмент проверяет пакет и обновляет lockfile; исходники библиотеки не собирает и не меняет. При смене версии заранее обновите зависимость и путь wheel в `pyproject.toml`. Весь проект библиотеки, тесты и документация находятся отдельно в OpenDoc. Пакет пока не опубликован в реестр; при распространении wheel самого TextAlchemy следует приложить wheel OpenDoc.
