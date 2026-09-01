from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from cryptography.fernet import Fernet

_PHONE_FINGERPRINT_PURPOSE = "employee-contact-phone:v1"


def normalize_phone(value: str) -> str:
    """Normalize a Chinese mobile or landline number without rejecting valid extensions."""
    raw = value.strip()
    extension = ""
    extension_match = re.search(r"(?:转|ext\.?|extension|x)\s*(\d{1,8})\s*$", raw, re.I)
    if extension_match:
        extension = extension_match.group(1)
        raw = raw[: extension_match.start()]
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0086"):
        digits = digits[4:]
    elif digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    if not 7 <= len(digits) <= 12:
        raise ValueError("phone number must contain 7 to 12 digits")
    # In domestic Chinese notation the leading zero is a trunk prefix, not
    # part of the E.164 national significant number.
    if digits.startswith("0"):
        digits = digits[1:]
    normalized = f"+86{digits}"
    return f"{normalized};ext={extension}" if extension else normalized


def mask_phone(normalized: str) -> str:
    main, _, extension = normalized.partition(";ext=")
    local = main.removeprefix("+86")
    if len(local) == 11 and local.startswith("1"):
        masked = f"{local[:3]}****{local[-4:]}"
    else:
        visible_start = min(4, max(2, len(local) - 6))
        masked = f"{local[:visible_start]}****{local[-4:]}"
    return f"{masked} 转 {extension}" if extension else masked


@dataclass(frozen=True)
class ProtectedPhone:
    normalized: str
    encrypted: str
    fingerprint: str
    masked: str


class ContactPhoneProtector:
    def __init__(self, *, encryption_key: str, hmac_key: str) -> None:
        self._cipher = Fernet(encryption_key.encode())
        self._hmac_key = hmac_key.encode()

    def fingerprint(self, value: str, *, purpose: str = _PHONE_FINGERPRINT_PURPOSE) -> str:
        normalized = normalize_phone(value)
        message = purpose.encode() + b"\0" + normalized.encode()
        return hmac.new(self._hmac_key, message, hashlib.sha256).hexdigest()

    def protect(self, value: str) -> ProtectedPhone:
        normalized = normalize_phone(value)
        return ProtectedPhone(
            normalized=normalized,
            encrypted=self._cipher.encrypt(normalized.encode()).decode(),
            fingerprint=self.fingerprint(normalized),
            masked=mask_phone(normalized),
        )

    def decrypt(self, encrypted: str) -> str:
        return self._cipher.decrypt(encrypted.encode()).decode()
