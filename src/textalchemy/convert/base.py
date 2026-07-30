from abc import ABC, abstractmethod
from pathlib import Path

from textalchemy.core.diagnostics import ConversionReport, IssueSeverity


class ConversionResult(ConversionReport):
    """Backward-compatible facade over :class:`ConversionReport`.

    New code should return ``ConversionReport`` directly. Existing converters
    may keep constructing ``ConversionResult(input, output, success, error)``.
    """

    def __init__(
        self,
        input_path: str | Path,
        output_path: str | Path,
        success: bool,
        error: str | None = None,
    ) -> None:
        super().__init__(Path(output_path))
        self.input_path = Path(input_path)
        if not success:
            self.add(IssueSeverity.ERROR, "conversion", error or "conversion failed")

    @property
    def error(self) -> str | None:
        return next(
            (issue.message for issue in self.issues if issue.severity is IssueSeverity.ERROR),
            None,
        )

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        payload["input_path"] = str(self.input_path)
        payload["error"] = self.error
        return payload


class BaseConverter(ABC):
    def _prepare(self, input_path: str | Path, output_path: str | Path) -> tuple[Path, Path] | None:
        """Общая проверка входа и создание выходной директории.

        Возвращает ``(input_path, output_path)`` или ``None``, если входа нет
        (тогда ошибка уже залогирована в caller через возврат ConversionResult).
        """
        in_p = Path(input_path)
        out_p = Path(output_path)
        if not in_p.exists():
            return None
        out_p.parent.mkdir(parents=True, exist_ok=True)
        return in_p, out_p

    @abstractmethod
    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionReport:
        ...
