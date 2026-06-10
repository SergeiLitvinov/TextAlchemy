import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class NamingConfig:
    template: str = "{index:02d}_{type}_{authors}_{title}"
    include_type: bool = True
    max_title_len: int = 50
    max_authors: int = 3
    separator: str = "_"
    transliterate_title: bool = False


@dataclass
class MatchingConfig:
    threshold: float = 0.30
    manual_matching_file: Optional[str] = None
    strict_mode: bool = False


@dataclass
class ReportConfig:
    format: str = "json"
    include_missing: bool = True
    include_unmatched: bool = True
    output: str = "report.json"


@dataclass
class Config:
    mode: str = "match"
    source: str = "./literature_files"
    output: str = "./output"
    bibliography: str = "bibliography.txt"
    naming: NamingConfig = field(default_factory=NamingConfig)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    report: ReportConfig = field(default_factory=ReportConfig)

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        naming = NamingConfig(**(data.get("naming", {})))
        matching = MatchingConfig(**(data.get("matching", {})))
        report = ReportConfig(**(data.get("report", {})))
        base = {k: v for k, v in data.items() if k not in ("naming", "matching", "report")}
        return cls(naming=naming, matching=matching, report=report, **base)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "source": self.source,
            "output": self.output,
            "bibliography": self.bibliography,
            "naming": {
                "template": self.naming.template,
                "include_type": self.naming.include_type,
                "max_title_len": self.naming.max_title_len,
                "max_authors": self.naming.max_authors,
                "separator": self.naming.separator,
                "transliterate_title": self.naming.transliterate_title,
            },
            "matching": {
                "threshold": self.matching.threshold,
                "manual_matching_file": self.matching.manual_matching_file,
                "strict_mode": self.matching.strict_mode,
            },
            "report": {
                "format": self.report.format,
                "include_missing": self.report.include_missing,
                "include_unmatched": self.report.include_unmatched,
                "output": self.report.output,
            },
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def generate_default_config() -> Config:
    return Config()
