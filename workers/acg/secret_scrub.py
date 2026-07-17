from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SAFE_SECRET_METADATA_KEYS = frozenset(
    {
        "hasapikey",
        "hasmodelapikey",
        "hasttsapikey",
        "haspassword",
        "hastoken",
        "hascookie",
        "hascredential",
    }
)

SENSITIVE_URL_QUERY_KEYS = frozenset(
    {
        "auth",
        "code",
        "jwt",
        "key",
        "session",
        "sessionid",
        "sig",
        "signature",
    }
)


def is_runtime_secret_key(key: Any) -> bool:
    compact = "".join(
        character.lower() for character in str(key) if character.isascii() and character.isalnum()
    )
    safe_metadata = (
        compact.endswith(("exists", "revision", "source", "reference", "ref"))
        or compact in SAFE_SECRET_METADATA_KEYS
    )
    if safe_metadata:
        return False
    return (
        "apikey" in compact
        or "authorization" in compact
        or "accesstoken" in compact
        or "refreshtoken" in compact
        or "bearertoken" in compact
        or "oauthtoken" in compact
        or "oauthcode" in compact
        or "authorizationcode" in compact
        or "clientsecret" in compact
        or "privatekey" in compact
        or (compact.startswith("token") and not compact.endswith(("type", "count", "expiry")))
        or compact in {"auth", "jwt", "session", "sessionid", "setcookie", "signature"}
        or compact.endswith(("sessionid", "sessiontoken", "signature"))
        or compact.endswith(
            ("password", "passphrase", "token", "secret", "cookie", "credential", "credentials")
        )
    )


def is_sensitive_url_query_key(key: Any) -> bool:
    compact = "".join(
        character.lower() for character in str(key) if character.isascii() and character.isalnum()
    )
    return compact in SENSITIVE_URL_QUERY_KEYS or is_runtime_secret_key(key)


def scrub_url_secrets(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return value
    if not parsed.netloc:
        return value
    netloc = parsed.netloc.rsplit("@", 1)[-1]

    def safe_component(component: str) -> str:
        if not component or "=" not in component:
            return component
        return urlencode(
            [
                (key, child)
                for key, child in parse_qsl(component, keep_blank_values=True)
                if not is_sensitive_url_query_key(key)
            ],
            doseq=True,
        )

    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            safe_component(parsed.query),
            safe_component(parsed.fragment),
        )
    )


def scrub_runtime_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "" if is_runtime_secret_key(key) else scrub_runtime_secrets(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [scrub_runtime_secrets(child) for child in value]
    if isinstance(value, tuple):
        return tuple(scrub_runtime_secrets(child) for child in value)
    if isinstance(value, str):
        return scrub_url_secrets(value)
    return value
