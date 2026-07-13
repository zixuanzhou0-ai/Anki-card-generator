"""Process-local aiohttp compatibility for the managed Hermes proxy.

Hermes 0.18.2 creates its proxy ClientSession without ``trust_env=True``.
When the desktop must reach xAI through an HTTP(S) proxy, enable this shim
only for the Hermes child process via ``ANKI_CARD_HERMES_TRUST_ENV=1``.
"""

from __future__ import annotations

import os


if os.environ.get("ANKI_CARD_HERMES_TRUST_ENV") == "1":
    import aiohttp

    _OriginalClientSession = aiohttp.ClientSession

    class _TrustEnvironmentClientSession(_OriginalClientSession):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("trust_env", True)
            super().__init__(*args, **kwargs)

    aiohttp.ClientSession = _TrustEnvironmentClientSession
