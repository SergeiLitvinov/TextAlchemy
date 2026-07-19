from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConversionResult:
    input_path: Path
    output_path: Path
    success: bool
    error: str | None = None


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
    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        ...
