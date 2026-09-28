"""Non-secret account settings and explicitly trusted OS keyring backends."""

import json
import os
import re
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from .errors import HatebloError

SERVICE = "hateblo-posting"
TRUSTED_BACKENDS = {
    "keyring.backends.Windows",
    "keyring.backends.macOS",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
}


def config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / SERVICE / "config.json"


def validate_account(user: str, blog: str) -> tuple[str, str]:
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", user):
        raise HatebloError("はてなIDを --user または HATENA_USER で指定してください。")
    if not isinstance(blog, str) or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", blog
    ):
        raise HatebloError("ブログID（URLではなく元のドメイン）を --blog で指定してください。")
    return user, blog


def account(user: str | None, blog: str | None) -> tuple[str, str]:
    settings = {}
    path = config_path()
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError
        except (ValueError, OSError) as exc:
            raise HatebloError(
                "アカウント設定を読み取れません。config.json を確認してください。"
            ) from exc
    return validate_account(
        user or os.environ.get("HATENA_USER") or settings.get("user", ""),
        blog or os.environ.get("HATENA_BLOG") or settings.get("blog", ""),
    )


def secure_backend():
    try:
        backend = keyring.get_keyring()
        candidates = (
            backend.backends
            if type(backend).__module__ == "keyring.backends.chainer"
            else [backend]
        )
        for candidate in candidates:
            if type(candidate).__module__ in TRUSTED_BACKENDS and candidate.priority > 0:
                return candidate
    except Exception as exc:
        raise HatebloError("OS資格情報ストアを初期化できません。") from exc
    raise HatebloError(
        "安全なOS資格情報ストアがありません。CIでは HATENA_API_KEY を利用してください。"
    )


def credential_id(user: str, blog: str) -> str:
    return f"{user}@{blog}"


def api_key(user: str, blog: str) -> str:
    secret = os.environ.get("HATENA_API_KEY")
    if secret is None:
        try:
            secret = secure_backend().get_password(SERVICE, credential_id(user, blog))
        except KeyringError as exc:
            raise HatebloError("OS資格情報ストアからAPIキーを読み取れません。") from exc
    if not secret or not secret.strip():
        raise HatebloError(
            "APIキーが未設定です。auth login または HATENA_API_KEY を利用してください。"
        )
    return secret


def login(user: str, blog: str, secret: str) -> None:
    validate_account(user, blog)
    if not secret or not secret.strip():
        raise HatebloError("空のAPIキーは保存できません。")
    try:
        secure_backend().set_password(SERVICE, credential_id(user, blog), secret)
    except KeyringError as exc:
        raise HatebloError("APIキーをOS資格情報ストアに保存できません。") from exc
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"user": user, "blog": blog}) + "\n", encoding="utf-8")
    temporary.replace(path)


def logout(user: str, blog: str) -> None:
    try:
        backend = secure_backend()
        if backend.get_password(SERVICE, credential_id(user, blog)) is not None:
            backend.delete_password(SERVICE, credential_id(user, blog))
    except KeyringError as exc:
        raise HatebloError("OS資格情報ストアのAPIキーを削除できません。") from exc
