"""Read optional YAML front matter without treating it as executable configuration."""

import re
from dataclasses import dataclass

import yaml

from .errors import HatebloError


@dataclass
class Document:
    metadata: dict
    body: str
    front_matter: str = ""


def parse_document(source: str) -> Document:
    source = source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not source.startswith("---\n"):
        return Document({}, source)
    match = re.search(r"(?m)^(?:---|\.\.\.)\s*$", source[4:])
    if not match:
        raise HatebloError("YAML front matter が閉じられていません。")
    end = 4 + match.end()
    if source[end : end + 1] == "\n":
        end += 1
    try:
        metadata = yaml.safe_load(source[4 : 4 + match.start()])
        if metadata is None:
            metadata = {}
    except yaml.YAMLError as exc:
        raise HatebloError("YAML front matter の書式が不正です。") from exc
    if not isinstance(metadata, dict):
        raise HatebloError("YAML front matter はキーと値の形式で指定してください。")
    for key in ("title", "slug", "custom_url"):
        if key in metadata and (not isinstance(metadata[key], str) or not metadata[key].strip()):
            raise HatebloError(f"front matter の {key} は空でない文字列にしてください。")
    for key in ("categories", "tags"):
        if key in metadata and (
            not isinstance(metadata[key], list)
            or not all(isinstance(item, str) and item.strip() for item in metadata[key])
        ):
            raise HatebloError(f"front matter の {key} は文字列の配列にしてください。")
    return Document(metadata, source[end:], source[:end])
