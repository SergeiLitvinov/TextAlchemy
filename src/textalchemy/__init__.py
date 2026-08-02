from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("textalchemy")
except PackageNotFoundError:  # Source tree used without installing the package.
    __version__ = "0+unknown"

__all__ = ["__version__"]
