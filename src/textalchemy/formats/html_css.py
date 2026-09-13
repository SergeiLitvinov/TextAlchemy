"""Bounded static CSS cascade; unsupported syntax is never silently accepted."""

from __future__ import annotations

import re

from textalchemy.core.document_model import Length, TextStyle

SELECTOR = re.compile(r"(?:[a-zA-Z][\w-]*|\*)?(?:[.#][\w-]+)*$")
INHERITED = {"color", "font-family", "font-size", "font-weight", "font-style", "text-align", "white-space"}
INITIAL = {"color": "#000000", "font-size": "12pt", "font-weight": "normal", "font-style": "normal", "white-space": "normal"}
ENUMS = {
    "font-weight": {"normal", "bold", "400", "600", "700", "800", "900"},
    "font-style": {"normal", "italic", "oblique"},
    "text-align": {"left", "right", "center", "justify"},
    "white-space": {"normal", "pre", "pre-wrap"},
    "text-decoration": {"none", "underline"},
    "vertical-align": {"baseline", "super", "sub"},
    "display": {"none"},
}


class Cascade:
    def __init__(self, soup, warn):
        import tinycss2

        self.warn, self.rules, self.cache = warn, [], {}
        for sheet in soup.find_all("style"):
            if sheet.get("media", "all") not in {"all", "screen", ""}:
                warn("html-css", "Условная таблица стилей не применена.")
                continue
            for rule in tinycss2.parse_stylesheet(sheet.get_text(), skip_comments=True, skip_whitespace=True):
                if rule.type != "qualified-rule":
                    warn("html-css", "Правило CSS вне первого среза: " + getattr(rule, "at_keyword", rule.type))
                    continue
                problems = []
                declarations = self.declarations(rule.content, lambda feature, message: problems.append((feature, message)))
                for selector in tinycss2.serialize(rule.prelude).split(","):
                    selector = selector.strip()
                    if not selector or not SELECTOR.fullmatch(selector):
                        warn("html-css", f"Селектор не применён: {selector}")
                    else:
                        specificity = (selector.count("#"), selector.count("."), int(selector[0].isalpha()))
                        self.rules.append((selector, specificity, declarations, problems))

    def declarations(self, raw, warn=None):
        import tinycss2

        warn = warn or self.warn
        result = []
        for item in tinycss2.parse_blocks_contents(raw, skip_comments=True, skip_whitespace=True):
            if item.type != "declaration":
                warn("html-css", "Некорректное или вложенное объявление CSS пропущено.")
                continue
            name, value = item.lower_name, tinycss2.serialize(item.value).strip()
            if name in ENUMS or value.lower() in {"inherit", "initial", "unset"}:
                value = value.lower()
            supported = name in ENUMS or name in {"color", "font-size", "font-family"}
            if not supported:
                warn("html-css", f"Свойство не поддержано: {name}")
                continue
            if name == "font-family" and re.search(r"[;{}()<>\\]", value):
                warn("html-css", "Сложное значение font-family не поддержано.")
                continue
            if name in ENUMS and value.lower() not in ENUMS[name] | {"inherit", "initial", "unset"}:
                warn("html-css", f"Значение не поддержано: {name}: {value}")
                continue
            result.append((name, value, item.important))
        return result

    def style(self, node):
        if id(node) in self.cache:
            return self.cache[id(node)]
        parent = self.style(node.parent) if getattr(node.parent, "name", None) else INITIAL
        style = {key: value for key, value in parent.items() if key in INHERITED}
        semantic = {
            "b": {"font-weight": "bold"},
            "strong": {"font-weight": "bold"},
            "th": {"font-weight": "bold"},
            "i": {"font-style": "italic"},
            "em": {"font-style": "italic"},
            "u": {"text-decoration": "underline"},
            "sup": {"vertical-align": "super"},
            "sub": {"vertical-align": "sub"},
            "pre": {"white-space": "pre"},
        }
        style.update(semantic.get(node.name, {}))
        if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            style.update({"font-weight": "bold", "font-size": f"{(24, 18, 14, 12, 10, 9)[int(node.name[1]) - 1]}pt"})
        winners = {}
        for order, (selector, specificity, declarations, problems) in enumerate(self.rules):
            if self.matches(node, selector):
                self._apply(winners, declarations, (0, *specificity, order))
                for feature, message in problems:
                    self.warn(feature, message, node)
        declarations = self.declarations(node.get("style", ""), lambda feature, message: self.warn(feature, message, node))
        self._apply(winners, declarations, (1, 0, 0, 0, len(self.rules)))
        for name, (_, value) in winners.items():
            if value == "inherit" or (value == "unset" and name in INHERITED):
                value = parent.get(name, INITIAL.get(name, ""))
            elif value in {"initial", "unset"}:
                value = INITIAL.get(name, "")
            style[name] = value
        size = style.get("font-size", "12pt")
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(pt|px|em|rem|%)", size)
        if match:
            number, unit = float(match[1]), match[2]
            parent_size = float(parent.get("font-size", "12pt")[:-2])
            root_size = (
                float(self.style(node.find_parent("html")).get("font-size", "12pt")[:-2]) if node.find_parent("html") else 12
            )
            points = number * {"pt": 1, "px": 0.75, "em": parent_size, "rem": root_size, "%": parent_size / 100}[unit]
            style["font-size"] = f"{points:g}pt"
        else:
            self.warn("html-css", f"Размер шрифта не поддержан: {size}", node)
            style["font-size"] = parent.get("font-size", "12pt")
        self.cache[id(node)] = style
        if parent.get("text-decoration") == "underline":
            style["text-decoration"] = "underline"
        return style

    @staticmethod
    def _apply(winners, declarations, specificity):
        for index, (name, value, important) in enumerate(declarations):
            rank = (int(important), *specificity, index)
            if name not in winners or rank >= winners[name][0]:
                winners[name] = rank, value

    @staticmethod
    def matches(node, selector):
        tag = re.match(r"^[\w-]+|^\*", selector)
        if tag and tag[0] != "*" and tag[0].lower() != node.name:
            return False
        return all(
            node.get("id") == name if marker == "#" else name in node.get("class", [])
            for marker, name in re.findall(r"([.#])([\w-]+)", selector)
        )

    def text_style(self, css, node=None):
        from tinycss2.color3 import parse_color

        def color(name):
            value = css.get(name)
            if not value:
                return None
            parsed = parse_color(value)
            if parsed == "currentColor":
                parsed = parse_color(css.get("color", "black"))
            if parsed is None or isinstance(parsed, str):
                self.warn("html-css", f"Цвет не поддержан: {name}: {value}", node)
                return None
            from textalchemy.core.color import ColorValue

            return ColorValue(space="srgb", components=(parsed.red, parsed.green, parsed.blue), alpha=parsed.alpha)

        return TextStyle(
            font_family=css.get("font-family", "").split(",")[0].strip(" '\"") or None,
            font_size=Length(float(css["font-size"][:-2])),
            bold=css.get("font-weight") in {"bold", "600", "700", "800", "900"},
            italic=css.get("font-style") in {"italic", "oblique"},
            underline=css.get("text-decoration") == "underline",
            superscript=css.get("vertical-align") == "super",
            subscript=css.get("vertical-align") == "sub",
            color=color("color"),
            background=color("background-color"),
        )
