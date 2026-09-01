#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path

import httpx


def request(method: str, path: str, payload: dict | None = None) -> object:
    base = os.getenv("EMPLOYEE_VIDEO_NOTIFICATION_API", "http://127.0.0.1:8091/api/v1")
    token = os.getenv("EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN", "")
    if not token:
        raise SystemExit("EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN is required")
    response = httpx.request(
        method,
        f"{base.rstrip('/')}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def upload_video(
    company_id: str | None,
    employee_id: str | None,
    file_path: str | None,
    title: str,
    caption: str,
) -> object:
    if not company_id or not employee_id or not file_path:
        raise SystemExit("upload_video requires --company-id, --employee-id, and --file")
    token = os.getenv("EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN", "")
    if not token:
        raise SystemExit("EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN is required")
    path = Path(file_path)
    if not path.is_file():
        raise SystemExit(f"Video file not found: {path}")
    base = os.getenv("EMPLOYEE_VIDEO_NOTIFICATION_API", "http://127.0.0.1:8091/api/v1")
    content_type = mimetypes.guess_type(path.name)[0] or ""
    if not content_type.startswith("video/"):
        raise SystemExit("--file must be a recognized video type")
    with path.open("rb") as stream:
        response = httpx.post(
            f"{base.rstrip('/')}/video-assets",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "company_id": company_id,
                "employee_id": employee_id,
                "title": title,
                "caption": caption,
            },
            files={"file": (path.name, stream, content_type)},
            timeout=120,
        )
    response.raise_for_status()
    return response.json()


def main() -> None:
    def upload_media() -> object:
        if not args.company_id or not args.employee_id or not args.file:
            raise SystemExit("upload_media requires --company-id, --employee-id, and --file")
        token = os.getenv("EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN", "")
        if not token:
            raise SystemExit("EMPLOYEE_VIDEO_NOTIFICATION_API_TOKEN is required")
        path = Path(args.file)
        if not path.is_file():
            raise SystemExit(f"Attachment file not found: {path}")
        base = os.getenv(
            "EMPLOYEE_VIDEO_NOTIFICATION_API", "http://127.0.0.1:8091/api/v1"
        )
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as stream:
            response = httpx.post(
                f"{base.rstrip('/')}/media-assets",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "company_id": args.company_id,
                    "employee_id": args.employee_id,
                    "title": args.title,
                    "caption": args.caption,
                },
                files={"file": (path.name, stream, content_type)},
                timeout=120,
            )
        response.raise_for_status()
        return response.json()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation",
        choices=[
            "authorized_companies",
            "list_targets",
            "preview",
            "send",
            "get_batch",
            "upload_media",
            "list_employees",
            "get_employee_profile",
            "upload_video",
            "create_notification",
            "create_video_delivery",
            "get_delivery_status",
        ],
    )
    parser.add_argument("--company-id")
    parser.add_argument("--company-slug")
    parser.add_argument("--target-code")
    parser.add_argument("--employee-id")
    parser.add_argument("--video-asset-id")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--caption", default="")
    parser.add_argument("--file")
    parser.add_argument("--delivery-id")
    parser.add_argument("--batch-id")
    parser.add_argument("--media-asset-id")
    parser.add_argument("--idempotency-key")
    args = parser.parse_args()
    if args.operation == "authorized_companies":
        result = request("GET", "authorized-companies")
    elif args.operation == "list_targets":
        result = request("GET", f"notification-targets?company_id={args.company_id}")
    elif args.operation == "preview":
        result = request(
            "POST",
            "notifications/preview",
            {"company_slug": args.company_slug, "target_code": args.target_code},
        )
    elif args.operation == "send":
        result = request(
            "POST",
            "notifications/send",
            {
                "company_slug": args.company_slug,
                "target_code": args.target_code,
                "title": args.title,
                "body": args.body,
                "media_asset_id": args.media_asset_id,
                "idempotency_key": args.idempotency_key,
            },
        )
    elif args.operation == "get_batch":
        result = request("GET", f"notification-batches/{args.batch_id}")
    elif args.operation == "upload_media":
        result = upload_media()
    elif args.operation == "list_employees":
        result = request("GET", f"employees?company_id={args.company_id}")
    elif args.operation == "get_employee_profile":
        result = request("GET", f"employees/{args.employee_id}")
    elif args.operation == "upload_video":
        result = upload_video(
            args.company_id,
            args.employee_id,
            args.file,
            args.title,
            args.caption,
        )
    elif args.operation in {"create_notification", "create_video_delivery"}:
        result = request(
            "POST",
            "deliveries",
            {
                "company_id": args.company_id,
                "employee_id": args.employee_id,
                "title": args.title,
                "body": args.body,
                "video_asset_id": args.video_asset_id,
                "idempotency_key": args.idempotency_key,
            },
        )
    elif args.operation == "get_delivery_status":
        result = request("GET", f"deliveries/{args.delivery_id}")
    else:
        raise SystemExit(f"Unsupported operation: {args.operation}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
