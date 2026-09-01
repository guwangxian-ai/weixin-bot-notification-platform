#!/usr/bin/env python3
from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def create_environment(template: Path, output: Path) -> tuple[str, str]:
    if output.exists():
        raise FileExistsError(f"{output} already exists; refusing to overwrite local secrets")

    username = "admin"
    password = secrets.token_urlsafe(18)
    replacements = {
        "APP_SECRET_KEY": secrets.token_urlsafe(48),
        "APP_IDENTIFIER_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "APP_IDENTIFIER_HMAC_KEY": secrets.token_urlsafe(48),
        "APP_BOT_WEBHOOK_SECRET": secrets.token_urlsafe(48),
        "APP_SERVICE_API_TOKEN": secrets.token_urlsafe(48),
        "APP_BOOTSTRAP_ADMIN_USERNAME": username,
        "APP_BOOTSTRAP_ADMIN_PASSWORD": password,
    }
    lines: list[str] = []
    for line in template.read_text(encoding="utf-8").splitlines():
        key, separator, _value = line.partition("=")
        if separator and key in replacements:
            line = f"{key}={replacements[key]}"
        lines.append(line)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)
    return username, password


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    output = root / ".env"
    username, password = create_environment(root / ".env.example", output)
    print(f"Created {output} with mode 0600")
    print(f"Initial administrator: {username}")
    print(f"Initial password: {password}")
    print("Save the password now and change it before production deployment.")


if __name__ == "__main__":
    main()
