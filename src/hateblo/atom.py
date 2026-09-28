"""Hatena AtomPub transport. Credentials never follow redirects or foreign links."""

from __future__ import annotations

import base64
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from .auth import validate_account
from .errors import HatebloError

ATOM = "http://www.w3.org/2005/Atom"
APP = "http://www.w3.org/2007/app"
HATENA = "http://www.hatena.ne.jp/info/xmlns#hatenablog"
NS = {"a": ATOM, "app": APP, "h": HATENA}
ET.register_namespace("", ATOM)
ET.register_namespace("app", APP)
ET.register_namespace("hatenablog", HATENA)
MAX_RESPONSE = 20 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_xml(data: bytes, expected: str | None = None) -> ET.Element:
    try:
        root = fromstring(data, forbid_dtd=True)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise HatebloError("APIから安全なAtom XMLを取得できませんでした。") from exc
    if expected and root.tag != f"{{{ATOM}}}{expected}":
        raise HatebloError("APIレスポンスのAtom要素が不正です。")
    return root


def entry_data(root: ET.Element) -> dict:
    links = {e.get("rel"): e.get("href") for e in root.findall("a:link", NS)}
    edit_url = links.get("edit", "") or ""
    content = root.find("a:content", NS)
    return {
        "id": urlsplit(edit_url).path.rsplit("/", 1)[-1] or root.findtext("a:id", "", NS),
        "title": root.findtext("a:title", "", NS),
        "content": root.findtext("a:content", "", NS),
        "content_type": content.get("type", "") if content is not None else "",
        "updated": root.findtext("a:updated", "", NS),
        "categories": [e.get("term", "") for e in root.findall("a:category", NS)],
        "draft": root.findtext("app:control/app:draft", "no", NS) == "yes",
        "links": links,
    }


def set_text(root: ET.Element, tag: str, value: str) -> None:
    element = root.find(tag)
    if element is None:
        element = ET.SubElement(root, tag)
    element.text = value


def entry_xml(
    title: str | None = None,
    content: str | None = None,
    categories: list[str] | None = None,
    draft: bool | None = None,
    custom_url: str | None = None,
    existing: ET.Element | None = None,
) -> bytes:
    # Update the fetched entry in place: preserve dates, publication state and controls.
    root = existing if existing is not None else ET.Element(f"{{{ATOM}}}entry")
    if title is not None:
        set_text(root, f"{{{ATOM}}}title", title)
    if content is not None:
        set_text(root, f"{{{ATOM}}}content", content)
        root.find(f"{{{ATOM}}}content").set("type", "text/plain")
    if categories is not None:
        for element in root.findall(f"{{{ATOM}}}category"):
            root.remove(element)
        for category in categories:
            ET.SubElement(root, f"{{{ATOM}}}category", {"term": category})
    if draft is not None:
        control = root.find(f"{{{APP}}}control")
        if control is None:
            control = ET.SubElement(root, f"{{{APP}}}control")
        set_text(control, f"{{{APP}}}draft", "yes" if draft else "no")
        # An explicit state change cancels scheduling inherited from the fetched entry.
        scheduled = control.find(f"{{{HATENA}}}scheduled")
        if scheduled is not None:
            scheduled.text = "no"
    if custom_url is not None:
        set_text(root, f"{{{HATENA}}}custom-url", custom_url)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


class Client:
    def __init__(self, user: str, blog: str, secret: str, *, opener=None):
        validate_account(user, blog)
        self.base = f"https://blog.hatena.ne.jp/{user}/{blog}/atom"
        self._authorization = "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode(
            "ascii"
        )
        self._opener = opener or urllib.request.build_opener(NoRedirect())

    def _safe_url(self, url: str) -> str:
        parsed = urlsplit(url)
        base = urlsplit(self.base)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "blog.hatena.ne.jp"
            or parsed.fragment
            or not (parsed.path == base.path or parsed.path.startswith(base.path + "/"))
            or "%" in parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or "\\" in url
            or any(ord(char) <= 32 for char in url)
        ):
            raise HatebloError("APIのリンクが許可されたブログの範囲外です。")
        return url

    def request(self, method: str, url: str, data: bytes | None = None) -> bytes:
        request = urllib.request.Request(
            self._safe_url(url),
            data=data,
            method=method,
            headers={
                "Authorization": self._authorization,
                "Accept": "application/atom+xml",
                "Content-Type": "application/atom+xml; charset=utf-8",
                "User-Agent": "hateblo-posting/0.1.0",
            },
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                result = response.read(MAX_RESPONSE + 1)
                if len(result) > MAX_RESPONSE:
                    raise HatebloError("APIレスポンスがサイズ上限を超えました。")
                return result
        except urllib.error.HTTPError as exc:
            hints = {
                401: "はてなIDとAPIキーを確認してください。",
                403: "ブログの権限を確認してください。",
                404: "ブログIDまたは記事IDを確認してください。",
                429: "時間をおいて再実行してください。",
            }
            # Never expose response bodies, URLs, or headers containing credentials.
            raise HatebloError(
                f"AtomPub HTTP {exc.code}: {hints.get(exc.code, '操作に失敗しました。')}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HatebloError(
                "APIへの通信に失敗しました。書き込み時は一覧で結果を確認してから再実行してください。"
            ) from exc

    def entry_url(self, entry_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9]+", entry_id):
            raise HatebloError("記事IDは英数字で指定してください。")
        return f"{self.base}/entry/{entry_id}"

    def get(self, entry_id: str) -> ET.Element:
        return parse_xml(self.request("GET", self.entry_url(entry_id)), "entry")

    def list(self, all_pages: bool = False) -> dict:
        url = f"{self.base}/entry"
        seen = set()
        entries = []
        while True:
            if url in seen:
                raise HatebloError("APIのページ送りが循環しています。")
            seen.add(url)
            root = parse_xml(self.request("GET", url), "feed")
            entries.extend(entry_data(e) for e in root.findall("a:entry", NS))
            link = root.find("a:link[@rel='next']", NS)
            next_url = urljoin(url, link.get("href", "")) if link is not None else None
            if next_url:
                self._safe_url(next_url)
                if urlsplit(next_url).path != urlsplit(f"{self.base}/entry").path:
                    raise HatebloError("記事一覧のページ送りURLが不正です。")
            if not all_pages or not next_url:
                return {"entries": entries, "next": next_url}
            url = next_url

    def create(self, data: bytes) -> dict:
        return entry_data(parse_xml(self.request("POST", f"{self.base}/entry", data), "entry"))

    def update(self, entry_id: str, data: bytes) -> dict:
        return entry_data(parse_xml(self.request("PUT", self.entry_url(entry_id), data), "entry"))

    def delete(self, entry_id: str) -> None:
        self.request("DELETE", self.entry_url(entry_id))

    def categories(self) -> list[str]:
        root = parse_xml(self.request("GET", f"{self.base}/category"))
        return [e.get("term", "") for e in root.findall(".//a:category", NS)]
