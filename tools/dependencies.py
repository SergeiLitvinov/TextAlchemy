"""Offline dependency inventory: exact lock coverage, profiles and licence evidence."""

import hashlib
import json
import re
import tomllib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inventory(root: Path = ROOT) -> tuple[list[dict], dict[str, set[tuple[str, str]]]]:
    """Include every lock branch; profiles conservatively retain platform/Python markers."""
    packages = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))["package"]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    metadata = json.loads((root / "contracts/dependencies.json").read_text(encoding="utf-8"))
    records = {(item["name"], item["version"]): item for item in metadata["packages"]}
    expected = {(item["name"], item["version"]) for item in packages if item["name"] != "textalchemy"}
    if len(records) != len(metadata["packages"]) or set(records) != expected:
        raise ValueError("Dependency licence inventory differs from uv.lock (missing, stale or duplicate records)")
    locked = {(item["name"], item["version"]): item for item in packages}
    for record in records.values():
        if not all(record.get(field) for field in ("description", "license", "evidence", "status")):
            raise ValueError(f"Incomplete dependency evidence: {record['name']}")
        if record["status"] not in {"declared", "license-file", "vendor-terms", "unresolved"}:
            raise ValueError(f"Invalid dependency evidence status: {record['name']}")
        if "UNKNOWN" in record["license"] and record["status"] != "unresolved":
            raise ValueError(f"Unknown dependency licence must remain unresolved: {record['name']}")
        inspected = record.get("inspected_wheel_sha256")
        if inspected and f"sha256:{inspected}" not in {
            wheel.get("hash") for wheel in locked[record["name"], record["version"]].get("wheels", [])
        }:
            raise ValueError(f"Inspected wheel differs from lock: {record['name']}")
        licence_files = [record['license_file']] if record.get('license_file') else []
        licence_files.extend(record.get('notice_files', []))
        for licence in licence_files:
            path = (root / licence["path"]).resolve()
            directory = (root / "doc/licenses").resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ValueError(f"Invalid dependency licence file: {record['name']}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != licence.get("sha256"):
                raise ValueError(f"Dependency licence file changed: {record['name']}")
    by_name = defaultdict(list)
    for package in packages:
        by_name[package["name"]].append(package)
    application = next(package for package in packages if package["name"] == "textalchemy")

    def closure(edges):
        found = set()
        visited = set()
        pending = list(edges)
        while pending:
            edge = pending.pop()
            extras = tuple(sorted(edge.get("extra", [])))
            for package in by_name[edge["name"]]:
                if edge.get("version") and package["version"] != edge["version"]:
                    continue
                key = package["name"], package["version"]
                state = key, extras
                if state in visited:
                    continue
                visited.add(state)
                found.add(key)
                pending.extend(package.get("dependencies", []))
                for extra in extras:
                    pending.extend(package.get("optional-dependencies", {}).get(extra, []))
        return found

    base = application.get("dependencies", [])
    profiles = {"base": closure(base)}
    for name, edges in application.get("optional-dependencies", {}).items():
        profiles[name] = closure([*base, *edges])
    build = project["build-system"]["requires"]
    profiles["build"] = set()
    for requirement in build:
        match = re.fullmatch(r"([\w-]+)==([\w.]+)", requirement)
        if not match or (match[1], match[2]) not in records:
            raise ValueError("Build dependencies must have exact versions and licence evidence in the lock")
        profiles["build"].add((match[1], match[2]))
    return sorted(records.values(), key=lambda item: (item["name"], item["version"])), profiles


def check_profile(name: str, root: Path = ROOT) -> None:
    """Fail on unresolved licences; this is not approval for dependency redistribution."""
    records, profiles = inventory(root)
    if name not in profiles:
        raise ValueError(f"Unknown dependency profile: {name}")
    unresolved = [item["name"] for item in records if (item["name"], item["version"]) in profiles[name]
                  and item["status"] == "unresolved"]
    if unresolved:
        raise ValueError("Unresolved dependency licences: " + ", ".join(unresolved))


def reference(root: Path = ROOT) -> str:
    records, profiles = inventory(root)
    lines = [
        "# Зависимости и лицензии", "",
        "Генерируется из `uv.lock` и проверенного реестра `contracts/dependencies.json`. "
        "Включены прямые, транзитивные, платформенные зависимости всех extras и сборочный backend. "
        "Один пакет может иметь две версии для разных Python. Это состав lockfile, а не установленного окружения.", "",
        "Назначения транзитивных пакетов приведены по метаданным авторов. Лицензия относится к пакету; "
        "нативные wheel, модели OCR и внешние программы могут включать дополнительные компоненты и условия. "
        "[Результаты и ограничения аудита](../development/licenses.md).", "",
        "## Профили", "", "| Профиль | Число записей вместе с базой | Неподтверждённые разрешения |",
        "|---|---|---|",
    ]
    for name, keys in sorted(profiles.items()):
        unresolved = ", ".join(f"{item['name']} {item['version']}" for item in records
                               if (item["name"], item["version"]) in keys and item["status"] == "unresolved")
        lines.append(f"| `{name}` | {len(keys)} | {unresolved or 'не выявлены'} |")
    lines += ["", "Профили обходят все ветви зависимостей без вычисления маркеров текущего компьютера. "
              "`ocr` может включать платформенные CUDA-компоненты; `build` содержит только backend сборки.", "",
              "## Полный реестр", "", "| Пакет / версия | Назначение | Лицензия | Основание | Профили |",
              "|---|---|---|---|---|"]
    for item in records:
        description = item["description"].replace("|", "&#124;").replace("\n", " ")
        license_label = item["license"].replace("|", "&#124;")
        uses = ", ".join(name for name, keys in sorted(profiles.items()) if (item["name"], item["version"]) in keys)
        lines.append(f"| `{item['name']} {item['version']}` | {description} | {license_label} | "
                     f"[{item['status']}]({item['evidence']}) | {uses or 'ветвь lockfile'} |")
    lines += ["", "`declared` — метаданные точной версии; `license-file` — текст лицензии выпущенного wheel; "
              "`vendor-terms` — условия производителя; `unresolved` — разрешение на распространение не установлено. "
              "Отсутствие лицензии не приравнивается к MIT.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    rows, groups = inventory()
    print(f"Verified {len(rows)} locked dependency records across {len(groups)} profiles")
