"""Yomitan-compatible dictionary import and lookup."""

from .models import BatchImportResult, DictionaryInfo, ImportFailure, ImportResult, LookupEntry
from .service import DictionaryService

__all__ = [
    "BatchImportResult",
    "DictionaryInfo",
    "DictionaryService",
    "ImportFailure",
    "ImportResult",
    "LookupEntry",
]
