"""ml_journal_suggester package."""

from importlib.metadata import PackageNotFoundError, version

try:  # pragma: no cover - metadata lookup
    __version__ = version("ml-journal-suggester")
except PackageNotFoundError:  # pragma: no cover - dev installs
    __version__ = "0.0.0"

__all__ = ["__version__"]
