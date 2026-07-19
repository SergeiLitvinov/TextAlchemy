from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from textalchemy.core.doc_types import DOC_TYPE_KEYWORDS, DOC_TYPES


@dataclass
class ClassificationResult:
    doc_type: str
    confidence: float
    scores: Dict[str, float]


class DocumentClassifier:
    DOC_TYPES = list(DOC_TYPES)

    def __init__(self, model_path: Optional[str] = None):
        if model_path:
            raise NotImplementedError("ML model loading is not implemented; classifier uses keyword matching")

    @property
    def is_available(self) -> bool:
        return True

    def classify(self, text: str) -> ClassificationResult:
        if not text.strip():
            return ClassificationResult("unknown", 0.0, {t: 0.0 for t in self.DOC_TYPES})

        text_lower = text.lower()
        scores: Dict[str, float] = {t: 0.0 for t in self.DOC_TYPES}

        for doc_type, kw_list in DOC_TYPE_KEYWORDS.items():
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
        except (LookupError, OSError):
            text = ""

        return self.classify(text)
