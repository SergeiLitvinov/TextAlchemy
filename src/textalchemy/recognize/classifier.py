from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    scores: Dict[str, float]


class DocumentClassifier:
    DOC_TYPES = [
        "article",
        "book",
        "dissertation",
        "monograph",
        "report",
        "abstract",
        "patent",
        "standard",
    ]

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = Path(model_path) if model_path else None
        self._model = None

    @property
    def is_available(self) -> bool:
        return self._model is not None

    def classify(self, text: str) -> ClassificationResult:
        if not text.strip():
            return ClassificationResult("unknown", 0.0, {t: 0.0 for t in self.DOC_TYPES})

        text_lower = text.lower()
        scores: Dict[str, float] = {t: 0.0 for t in self.DOC_TYPES}

        keywords = {
            "article": ["статья", "журнал", "doi", "abstract", "introduction", "conclusion"],
            "book": ["учебник", "учебное пособие", "издательство", "isbn", "том"],
            "dissertation": ["диссертация", "дис.", "кандидат", "доктор", "автореферат"],
            "monograph": ["монография", "научное издание"],
            "report": ["отчет", "report", "нтр"],
            "abstract": ["автореферат", "реферат", "abstract"],
            "patent": ["патент", "пат.", "изобретение"],
            "standard": ["стандарт", "гост", "snip", "snip"],
        }

        for doc_type, kw_list in keywords.items():
            match_count = sum(1 for kw in kw_list if kw in text_lower)
            if match_count > 0:
                scores[doc_type] = min(1.0, match_count / max(len(kw_list), 1) * 2)

        best_type = max(scores, key=lambda k: scores[k])  # type: ignore[arg-type]
        best_score = scores[best_type]

        return ClassificationResult(
            doc_type=best_type if best_score > 0 else "unknown",
            confidence=best_score,
            scores=scores,
        )

    def classify_file(self, file_path: str | Path) -> ClassificationResult:
        file_path = Path(file_path)
        if not file_path.exists():
            return ClassificationResult("unknown", 0.0, {t: 0.0 for t in self.DOC_TYPES})

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file_path.read_text(encoding="cp1251")
        except Exception:
            text = ""

        return self.classify(text)
