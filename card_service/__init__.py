"""Headless, local-only supervision boundary for the legacy card worker."""

from .service import CardService, CardServiceError

__all__ = ["CardService", "CardServiceError"]
