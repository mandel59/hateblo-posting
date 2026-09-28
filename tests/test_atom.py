import io
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET

import pytest

from hateblo.atom import APP, ATOM, HATENA, NS, Client, NoRedirect, entry_data, entry_xml, parse_xml
from hateblo.errors import HatebloError

BASE = "https://blog.hatena.ne.jp/alice/alice.hatenablog.com/atom"
ENTRY = f'''<entry xmlns="{ATOM}" xmlns:app="{APP}" xmlns:h="{HATENA}">
<id>tag:example:1</id><link rel="edit" href="{BASE}/entry/123"/>
<title>前のタイトル</title><content type="text/x-markdown">$x$</content>
<category term="数学"/><updated>2020-01-01T00:00:00+09:00</updated>
<app:control><app:draft>yes</app:draft><app:preview>yes</app:preview>
<h:scheduled>yes</h:scheduled></app:control>
<h:custom-url>original</h:custom-url></entry>'''.encode()


class Opener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        assert timeout == 30
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)


def test_crud_transport_and_unicode():
    opener = Opener(ENTRY, ENTRY, ENTRY, b"")
    client = Client("alice", "alice.hatenablog.com", "secret", opener=opener)
    assert entry_data(client.get("123"))["title"] == "前のタイトル"
    payload = entry_xml("日本語 & <xml>", "本文 $x$", ["A&B"], True)
    assert client.create(payload)["id"] == "123"
    client.update("123", payload)
    client.delete("123")
    assert [r.method for r in opener.requests] == ["GET", "POST", "PUT", "DELETE"]
    assert opener.requests[1].full_url == BASE + "/entry"
    assert opener.requests[1].data == payload
    assert opener.requests[0].get_header("Authorization") == "Basic YWxpY2U6c2VjcmV0"
    assert "secret" not in repr(client)
    root = parse_xml(payload, "entry")
    assert root.findtext("a:title", namespaces=NS) == "日本語 & <xml>"
    assert root.find("a:category", NS).get("term") == "A&B"
    assert root.findtext("app:control/app:draft", namespaces=NS) == "yes"


def test_update_preserves_unspecified_fields():
    root = parse_xml(entry_xml(title="new", existing=parse_xml(ENTRY)))
    assert root.findtext("a:content", namespaces=NS) == "$x$"
    assert root.find("a:content", NS).get("type") == "text/x-markdown"
    assert root.findtext("app:control/app:draft", namespaces=NS) == "yes"
    assert root.findtext("app:control/app:preview", namespaces=NS) == "yes"
    assert root.findtext("app:control/h:scheduled", namespaces=NS) == "yes"
    assert root.findtext("a:updated", namespaces=NS) == "2020-01-01T00:00:00+09:00"
    assert root.find("a:category", NS).get("term") == "数学"
    assert root.findtext("h:custom-url", namespaces=NS) == "original"


def test_explicit_state_cancels_schedule_and_clears_categories():
    root = parse_xml(entry_xml(draft=False, categories=[], existing=parse_xml(ENTRY)))
    assert root.findtext("app:control/app:draft", namespaces=NS) == "no"
    assert root.findtext("app:control/h:scheduled", namespaces=NS) == "no"
    assert root.findall("a:category", NS) == []


def feed(next_url=None):
    root = ET.Element(f"{{{ATOM}}}feed")
    root.append(parse_xml(ENTRY))
    if next_url:
        ET.SubElement(root, f"{{{ATOM}}}link", {"rel": "next", "href": next_url})
    return ET.tostring(root)


def test_pagination():
    opener = Opener(feed("?page=2"), feed())
    result = Client("alice", "alice.hatenablog.com", "secret", opener=opener).list(True)
    assert len(result["entries"]) == 2
    assert result["next"] is None
    assert opener.requests[1].full_url == BASE + "/entry?page=2"


def test_single_page_and_categories():
    opener = Opener(
        feed("?page=2"),
        (
            f'<categories xmlns="{APP}" xmlns:a="{ATOM}"><a:category term="数学"/></categories>'
        ).encode(),
    )
    client = Client("alice", "alice.hatenablog.com", "secret", opener=opener)
    assert client.list()["next"] == BASE + "/entry?page=2"
    assert client.categories() == ["数学"]


@pytest.mark.parametrize(
    "url",
    [
        "http://blog.hatena.ne.jp/alice/alice.hatenablog.com/atom/entry",
        "https://evil.test/entry",
        BASE.replace("alice/", "bob/") + "/entry",
        BASE + "/entry/../../../other",
        BASE + "/entry/%2e%2e/other",
        BASE + "/category",
        "https://blog.hatena.ne.jp@evil.test/entry",
    ],
)
def test_unsafe_pagination_never_receives_credentials(url):
    opener = Opener(feed(url))
    with pytest.raises(HatebloError):
        Client("alice", "alice.hatenablog.com", "secret", opener=opener).list(True)
    assert len(opener.requests) == 1


def test_pagination_loop():
    opener = Opener(feed(BASE + "/entry"))
    with pytest.raises(HatebloError, match="循環"):
        Client("alice", "alice.hatenablog.com", "secret", opener=opener).list(True)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 404, 429, 500])
def test_http_errors_redact_details(status):
    error = urllib.error.HTTPError(BASE, status, "secret", {}, io.BytesIO(b"secret"))
    opener = Opener(error)
    with pytest.raises(HatebloError) as info:
        Client("alice", "alice.hatenablog.com", "secret", opener=opener).get("123")
    assert str(status) in str(info.value)
    assert "secret" not in str(info.value)
    assert len(opener.requests) == 1


def test_redirect_handler_does_not_forward():
    request = urllib.request.Request(BASE, headers={"Authorization": "secret"})
    assert NoRedirect().redirect_request(request, None, 302, "", {}, "https://evil.test") is None


@pytest.mark.parametrize(
    "data", [b"<not-xml", b"<entry/>", b'<!DOCTYPE entry [<!ENTITY x "secret">]><entry>&x;</entry>']
)
def test_reject_bad_xml(data):
    with pytest.raises(HatebloError):
        parse_xml(data, "entry")


@pytest.mark.parametrize("entry_id", ["../other", "https://evil.test", "123?x=1", "", "a/b"])
def test_invalid_id(entry_id):
    with pytest.raises(HatebloError):
        Client("alice", "alice.hatenablog.com", "secret").entry_url(entry_id)
