from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient


def test_built_index_assets_are_served_with_correct_mime(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    asset_urls = re.findall(r'(?:src|href)="(\.?/assets/[^"]+)"', index.text)
    assert asset_urls, index.text

    for url in asset_urls:
        normalized = url.removeprefix(".")
        response = client.get(normalized)
        assert response.status_code == 200, normalized
        assert response.headers["content-type"].split(";", 1)[0] in {
            "application/javascript",
            "text/javascript",
            "text/css",
        }
        assert not response.text.lstrip().startswith('{"detail"')


def test_user_management_owns_weixin_binding_actions() -> None:
    source = Path("web/src/App.tsx").read_text(encoding="utf-8")

    assert "['employees', '用户管理', Users]" in source
    assert "['bindings', '微信绑定'" not in source
    assert "function BindingPanel" not in source

    user_panel = source.split("function EmployeePanel", 1)[1].split(
        "function BindingModal", 1
    )[0]
    assert "生成/刷新二维码" in user_panel
    assert "查看二维码" in user_panel
    assert "解除绑定" in user_panel
    assert "转交" in user_panel
    assert "测试发送" in user_panel
    assert "test-notification" in user_panel
    assert "manual_test" in user_panel


def test_admin_ui_only_shows_notification_logs_without_video_assets() -> None:
    source = Path("web/src/App.tsx").read_text(encoding="utf-8")

    assert "['assets', '视频资产'" not in source
    assert "api(`video-assets?company_id=${company}`)" not in source
    assert "function NotificationPanel" not in source
    assert "['deliveries', '通知日志', BellRing]" in source
    assert 'if(section===\'deliveries\') return <Panel title="通知日志">' in source


def test_general_platform_ui_has_required_information_architecture_and_mobile_styles() -> None:
    source = Path("web/src/GeneralPlatformApp.tsx").read_text(encoding="utf-8")
    entrypoint = Path("web/src/main.tsx").read_text(encoding="utf-8")
    styles = Path("web/src/platform.css").read_text(encoding="utf-8")

    assert "GeneralPlatformApp" in entrypoint
    assert "<PlatformApp" not in entrypoint
    for label in ("总览", "公司管理", "用户对象", "通知任务", "应用接入"):
        assert label in source
    assert "['bots','微信 Bot'" not in source
    assert "function Bots(" not in source
    user_objects = source.split("function UserObjects", 1)[1].split(
        "function Clients", 1
    )[0]
    for label in (
        "添加联系人",
        "生成二维码",
        "编辑",
        "逐 Bot 安全测试",
        "从当前对象移除",
        "解绑",
        "绑定全部可用 Bot",
        "停用",
        "删除",
    ):
        assert label in user_objects
    assert "companies/${company}/user-objects" in source
    assert "target_code" not in user_objects
    assert "dynamic_all" not in user_objects
    assert "绿色家装饰 · 业务系统" not in source
    assert "装修" not in source
    assert "company_slug" in source
    assert "target_code" in source
    assert "Token 仅显示这一次" in source
    assert "部分成功" in source
    assert "@media(max-width:900px)" in styles
    assert "@media(max-width:600px)" in styles
    mobile_styles = styles.split("@media(max-width:600px)", 1)[1]
    assert ".logout{display:none}" not in mobile_styles
    assert 'aria-label="退出登录"' in source
    assert "aria-label={label}" in source
    assert "refreshGeneration" in source
    assert '<Content key={`${company}:${section}`}' in source
    assert "evnc:unauthorized" in source
    assert "contact.binding_session&&" in source
    assert "['pending','scanned','confirming']" in source
