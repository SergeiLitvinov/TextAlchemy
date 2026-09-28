"""Static code/navigation inventory; never imports application or optional backends."""
import ast
import re
from collections import defaultdict
from pathlib import Path


def cell(value):
    return str(value).replace('|', '&#124;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', ' ')


def module_name(path, source):
    parts = list(path.relative_to(source.parent).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def imports(tree, module, package=False):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = module.split('.') if package else module.split('.')[:-1]
            base = '.'.join(prefix[:len(prefix) - node.level + 1]) if node.level else ''
            target = '.'.join(filter(None, (base, node.module)))
            yield target
            yield from (target + '.' + alias.name for alias in node.names)


def resolve_imports(tree, module, modules, package=False):
    found = set()
    for name in imports(tree, module, package):
        while name:
            if name in modules:
                if name != module:
                    found.add(name)
                break
            name = name.rpartition('.')[0]
    return sorted(found)


def anchor(module):
    return module.replace('.', '-')


def source_link(root, path):
    relative = path.relative_to(root).as_posix()
    return f'[{relative}](../../{relative})'


def routes(tree):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr
            if method not in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'websocket'}:
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                yield method.upper(), decorator.args[0].value, node.name, node.lineno


def code_pages(root: Path, notice: str):
    source = root / 'src/textalchemy'
    modules = {module_name(path, source): (path, ast.parse(path.read_text(encoding='utf-8-sig')))
               for path in sorted(source.rglob('*.py'))}
    tests = defaultdict(set)
    for path in sorted((root / 'tests').rglob('test_*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for module in resolve_imports(tree, 'tests.' + path.stem, modules):
            tests[module].add(path)
    groups = defaultdict(list)
    for module, (path, _) in modules.items():
        group = 'package' if path.parent == source else path.relative_to(source).parts[0]
        groups[group].append(module)
    lines = ['# Навигатор по коду', '',
             'Сформирован из AST Python и файлов Web. Код приложения не исполняется. '
             '[Руководство пользователя](user-guide.md) · [Web-маршруты](web-routes.md).', '',
             'Ссылки на тесты означают прямой статический импорт, а не покрытие или гарантию проверки. '
             'Динамические импорты и вызовы по реестру не восстанавливаются. '
             'Список символов включает определения верхнего уровня без начального подчёркивания.', '',
             '| Подсистема | Модулей |', '|---|---|']
    for group, names in sorted(groups.items()):
        lines.append(f'| [{group}](#area-{group}) | {len(names)} |')
    endpoints = []
    for group, names in sorted(groups.items()):
        lines += ['', f'<a id="area-{group}"></a>', f'## {group}', '']
        for module in names:
            path, tree = modules[module]
            lines += [f'<a id="{anchor(module)}"></a>', f'### {module}', '', source_link(root, path), '']
            doc = ast.get_docstring(tree)
            if doc:
                lines += [cell(doc.splitlines()[0]), '']
            relative = path.relative_to(root).as_posix()
            symbols = [f'[{node.name} ({node.lineno})](../../{relative}#L{node.lineno})' for node in tree.body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                       and not node.name.startswith('_')]
            lines += ['Символы (строка): ' + (', '.join(symbols) or 'нет публичных определений верхнего уровня') + '.', '']
            dependencies = resolve_imports(tree, module, modules, path.name == '__init__.py')
            if dependencies:
                lines += ['Импорты: ' + ', '.join(f'[{name}](#{anchor(name)})' for name in dependencies) + '.', '']
            if tests[module]:
                links = ', '.join(source_link(root, test) for test in sorted(tests[module]))
                lines += ['Прямые импорты в тестах: ' + links + '.', '']
            endpoints.extend((method, url, module, handler, line) for method, url, handler, line in routes(tree))
    lines += ['## Файлы интерфейса', '', '| Файл |', '|---|']
    for path in sorted((source / 'web').rglob('*')):
        if path.suffix in {'.js', '.html', '.css'}:
            lines.append(f'| {source_link(root, path)} |')
    route_lines = ['# Web-маршруты', '',
                   'Статически извлечённые HTTP/WebSocket-декораторы. '
                   'Это указатель обработчиков, не схема запросов и не OpenAPI. '
                   '[Пользовательские действия](../guide/index.md) · [Карта кода](code.md).', '',
                   '| Метод | Путь | Обработчик | Строка |', '|---|---|---|---|']
    for method, url, module, handler, line in sorted(endpoints):
        route_lines.append(f'| {method} | `{cell(url)}` | [{module}.{handler}](code.md#{anchor(module)}) | {line} |')
    return {'docs/reference/code.md': notice + '\n'.join(lines) + '\n',
            'docs/reference/web-routes.md': notice + '\n'.join(route_lines) + '\n'}


def user_guide(root: Path, notice: str):
    from markdown.extensions.toc import slugify_unicode

    lines = ['# Руководство пользователя — навигация', '',
             'Выберите задачу. Содержание формируется из глав руководства; '
             'сами инструкции и ограничения поддерживаются в этих главах и проверяются на исполняемых примерах.', '']
    for filename in ('index.md', 'formats.md', 'web-details.md'):
        text = (root / 'docs/guide' / filename).read_text(encoding='utf-8')
        text = re.sub(r'^```.*?^```[^\n]*', '', text, flags=re.M | re.S)
        title = re.search(r'^# (.+)$', text, re.M)[1]
        lines += [f'## {title}', '']
        for heading in re.finditer(r'^## (.+)$', text, re.M):
            title = heading[1]
            if title != 'Содержание':
                lines.append(f'- [{title}](../guide/{filename}#{slugify_unicode(title, "-")})')
        lines.append('')
    return notice + '\n'.join(lines)
