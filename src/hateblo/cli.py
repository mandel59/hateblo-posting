"""Command-line interface. stdout contains only the requested document or JSON."""

import argparse
import getpass
import json
import sys
import warnings
from pathlib import Path

from . import auth
from .atom import Client, entry_data, entry_xml
from .document import parse_document
from .errors import HatebloError
from .markdown import convert_math


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="はてなブログの記事操作とMarkdown数式変換")
    root.add_argument("--user", help="はてなID（省略時: HATENA_USER / 保存設定）")
    root.add_argument("--blog", help="ブログID（省略時: HATENA_BLOG / 保存設定）")
    root.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    commands = root.add_subparsers(dest="command", required=True)
    credentials = commands.add_parser("auth", help="OS資格情報ストアのAPIキー管理")
    actions = credentials.add_subparsers(dest="action", required=True)
    actions.add_parser("login", help="APIキーを非表示入力で保存する")
    for action in ("logout", "status"):
        actions.add_parser(action)
    convert = commands.add_parser("convert", help="ネットワークを使わず数式を変換")
    convert.add_argument("file", help="Markdownファイル。- は標準入力")
    convert.add_argument("-o", "--output", help="出力先（省略時: 標準出力）")
    convert.add_argument("--strip-front-matter", action="store_true")
    convert.add_argument("--no-dollar-math", action="store_true", help="ドル区切りを変換しない")
    convert.add_argument(
        "--math-compat",
        choices=("warn", "strict", "off"),
        default="warn",
        help="既知の数式互換変換: warn=変換と警告 / strict=診断時に停止 / off=無効",
    )
    commands.add_parser("list", help="記事一覧をJSON出力").add_argument(
        "--all", action="store_true", help="全ページを取得する"
    )
    get = commands.add_parser("get", help="記事をJSONまたは本文で取得")
    get.add_argument("id", help="記事ID")
    get.add_argument("--body", action="store_true", help="本文のみ出力")
    commands.add_parser("categories", help="カテゴリ一覧をJSON出力")
    for name in ("create", "update"):
        command = commands.add_parser(
            name, help="記事を新規作成" if name == "create" else "記事を更新"
        )
        if name == "update":
            command.add_argument("id", help="記事ID")
        command.add_argument(
            "file", nargs=None if name == "create" else "?", help="Markdown。- は標準入力"
        )
        command.add_argument("--title")
        categories = command.add_mutually_exclusive_group()
        categories.add_argument("--category", action="append", help="カテゴリ（繰り返し指定可）")
        categories.add_argument("--clear-categories", action="store_true")
        state = command.add_mutually_exclusive_group()
        state.add_argument("--publish", action="store_true", help="明示的に公開する")
        state.add_argument("--draft", action="store_true", help="下書きにする")
        command.add_argument("--custom-url", help="カスタムURLのパス")
        command.add_argument("--no-convert", action="store_true", help="本文の数式を変換しない")
        command.add_argument("--no-dollar-math", action="store_true")
        command.add_argument(
            "--math-compat",
            choices=("warn", "strict", "off"),
            default="warn",
            help="既知の数式互換変換: warn=変換と警告 / strict=診断時に停止 / off=無効",
        )
        command.add_argument(
            "--dry-run", action="store_true", help="送信予定XMLを表示し、書き込まない"
        )
    delete = commands.add_parser("delete", help="記事を削除")
    delete.add_argument("id")
    delete.add_argument("--yes", action="store_true", help="削除を明示的に承認")
    return root


def read_text(file: str) -> str:
    return sys.stdin.read() if file == "-" else Path(file).read_text(encoding="utf-8-sig")


def emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def make_client(args) -> Client:
    user, blog = auth.account(args.user, args.blog)
    return Client(user, blog, auth.api_key(user, blog))


def convert_document(document, args) -> str:
    diagnostics = []
    try:
        return convert_math(
            document.body,
            dollar_math=not args.no_dollar_math,
            math_compat=args.math_compat,
            diagnostics=diagnostics,
        )
    finally:
        for finding in diagnostics:
            print(finding.format(args.file, document.front_matter.count("\n")), file=sys.stderr)


def write_entry(args) -> None:
    document = parse_document(read_text(args.file)) if args.file else None
    meta = document.metadata if document else {}
    title = args.title if args.title is not None else meta.get("title")
    categories = args.category
    if args.clear_categories:
        categories = []
    elif categories is None:
        categories = meta.get("categories", meta.get("tags"))
    custom_url = (
        args.custom_url if args.custom_url is not None else meta.get("custom_url", meta.get("slug"))
    )
    if title is not None and not title.strip():
        raise HatebloError("タイトルは空にできません。")
    if custom_url is not None and not custom_url.strip():
        raise HatebloError("カスタムURLは空にできません。")
    content = document.body if document else None
    if content is not None and not args.no_convert:
        content = convert_document(document, args)
    draft = False if args.publish else True if args.draft else None
    client, existing = None, None
    if args.command == "create":
        if title is None:
            raise HatebloError("--title または front matter の title が必要です。")
        if draft is None:
            draft = True
    else:
        if all(value is None for value in (title, content, categories, draft, custom_url)):
            raise HatebloError("更新する本文またはオプションを指定してください。")
        client = make_client(args)
        existing = client.get(args.id)
        if content is not None and not args.no_convert:
            if entry_data(existing)["content_type"] != "text/x-markdown":
                raise HatebloError(
                    "更新先がMarkdownモードではありません。"
                    "元の記法で --no-convert を指定してください。"
                )
    data = entry_xml(title, content, categories, draft, custom_url, existing)
    if args.dry_run:
        print(data.decode("utf-8"))
        return
    client = client or make_client(args)
    emit(client.create(data) if args.command == "create" else client.update(args.id, data))


def run(args) -> None:
    if args.command == "convert":
        document = parse_document(read_text(args.file))
        result = ("" if args.strip_front_matter else document.front_matter) + convert_document(
            document, args
        )
        if args.output:
            Path(args.output).write_text(result, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(result)
        return
    if args.command == "auth":
        user, blog = auth.account(args.user, args.blog)
        if args.action == "login":
            if not sys.stdin.isatty():
                raise HatebloError(
                    "auth login は対話端末で実行してください。"
                    "CIでは HATENA_API_KEY を利用できます。"
                )
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    secret = getpass.getpass("はてなブログ APIキー: ")
                except getpass.GetPassWarning as exc:
                    raise HatebloError(
                        "APIキーを非表示で入力できる端末を利用してください。"
                    ) from exc
            auth.login(user, blog, secret)
            emit({"stored": True, "user": user, "blog": blog})
        elif args.action == "logout":
            auth.logout(user, blog)
            emit({"removed": True, "note": "HATENA_API_KEY は環境変数側で解除してください。"})
        else:
            auth.api_key(user, blog)
            emit({"configured": True, "user": user, "blog": blog})
        return
    if args.command in {"create", "update"}:
        write_entry(args)
        return
    if args.command == "delete" and not args.yes:
        raise HatebloError("削除するには --yes を指定してください。")
    client = make_client(args)
    if args.command == "list":
        emit(client.list(args.all))
    elif args.command == "get":
        entry = entry_data(client.get(args.id))
        if args.body:
            sys.stdout.write(entry["content"])
        else:
            emit(entry)
    elif args.command == "categories":
        emit(client.categories())
    elif args.command == "delete":
        client.delete(args.id)
        emit({"deleted": args.id})


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        run(args)
        return 0
    except HatebloError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print(
            "error: UTF-8ファイルの入出力に失敗しました。パスと権限を確認してください。",
            file=sys.stderr,
        )
        return 1
    except (KeyboardInterrupt, EOFError):
        print("error: 操作を中断しました。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
