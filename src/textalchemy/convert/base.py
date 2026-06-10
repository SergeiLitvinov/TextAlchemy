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
    @abstractmethod
    def convert(self, input_path: str | Path, output_path: str | Path) -> ConversionResult:
        ...
