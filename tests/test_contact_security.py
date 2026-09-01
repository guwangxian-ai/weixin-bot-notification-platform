from __future__ import annotations

from cryptography.fernet import Fernet

from app.contact_security import ContactPhoneProtector, normalize_phone


def test_normalize_phone_accepts_chinese_mobile_landline_and_extensions() -> None:
    assert normalize_phone("138 0013 8000") == "+8613800138000"
    assert normalize_phone("+86 138-0013-8000") == "+8613800138000"
    assert normalize_phone("010-88886666 转 123") == "+861088886666;ext=123"
    assert normalize_phone("0755 8888 6666 ext. 42") == "+8675588886666;ext=42"


def test_contact_phone_protection_encrypts_masks_and_uses_purpose_isolated_hmac() -> None:
    protector = ContactPhoneProtector(
        encryption_key=Fernet.generate_key().decode(),
        hmac_key="test-hmac-key-that-is-long-enough-123",
    )

    protected = protector.protect("13800138000")

    assert protected.normalized == "+8613800138000"
    assert protected.masked == "138****8000"
    assert "13800138000" not in protected.encrypted
    assert protector.decrypt(protected.encrypted) == "+8613800138000"
    assert protected.fingerprint != protector.fingerprint("13800138000", purpose="other-purpose")
