# Контракты и план OpenDoc Formats

OpenDoc Formats владеет контрактами доступа к форматам и своим активным планом.
Эта страница — навигация из документации приложения; библиотечные задачи здесь не дублируются.

- [Публичный контракт PDF, офисного предпросмотра и правок DOCX](https://github.com/SergeiLitvinov/opendoc-formats/blob/main/docs/development/native-access-contract.md).
- [Состояние запросов OF01–OF05](https://github.com/SergeiLitvinov/opendoc-formats/blob/main/docs/development/format-requests.md).
- [Подтверждённые задачи библиотеки](https://github.com/SergeiLitvinov/opendoc-formats/blob/main/docs/development/todo.md) и [исследования](https://github.com/SergeiLitvinov/opendoc-formats/blob/main/docs/development/research.md).
- [Документация и план библиотеки](https://SergeiLitvinov.github.io/opendoc-formats/).
- [Исходный проект и документы разработки](https://github.com/SergeiLitvinov/opendoc-formats/tree/main/docs/development).

Прежние запросы OF-01/OF-02 закрыты публичными API библиотеки; оставшиеся OF-03–OF-05
переданы в её проект для аудита и дальнейшего развития. Их состояние проверяется у владельца,
а приложение планирует интеграцию опубликованных возможностей и пользовательскую приёмку.

Новый пробел передаётся владельцу с версией, вызывающим сценарием, разрешённым примером,
ожидаемым результатом, диагностикой, лимитами/отменой и критериями совместимости.
Сначала библиотека согласует и выпускает API, затем TextAlchemy обновляет wheel,
контрольную сумму и lockfile. Заплатки в установленном пакете и обходы движков запрещены.
