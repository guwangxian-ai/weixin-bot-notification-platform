from pathlib import Path

import pytest

from scripts.bootstrap_env import create_environment


def test_create_environment_generates_secrets_and_refuses_overwrite(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    output = tmp_path / ".env"
    template.write_text(
        "APP_SECRET_KEY=replace-with-at-least-32-random-characters\n"
        "APP_IDENTIFIER_ENCRYPTION_KEY=replace-with-fernet-key\n"
        "APP_IDENTIFIER_HMAC_KEY=replace-with-at-least-32-random-characters\n"
        "APP_BOT_WEBHOOK_SECRET=replace-with-at-least-32-random-characters\n"
        "APP_SERVICE_API_TOKEN=replace-with-at-least-32-random-characters\n"
        "APP_BOOTSTRAP_ADMIN_USERNAME=admin\n"
        "APP_BOOTSTRAP_ADMIN_PASSWORD=replace-with-a-strong-password\n",
        encoding="utf-8",
    )

    username, password = create_environment(template, output)

    content = output.read_text(encoding="utf-8")
    assert username == "admin"
    assert password in content
    assert "replace-with" not in content
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        create_environment(template, output)
