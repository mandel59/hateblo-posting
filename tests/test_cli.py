import io

import pytest
from test_atom import ENTRY

from hateblo import cli
from hateblo.atom import NS, parse_xml


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.setattr(cli, "make_client", lambda args: pytest.fail("unexpected API call"))


def test_offline_dry_run_defaults_to_draft(tmp_path, capsys):
    article = tmp_path / "article.md"
    article.write_text("---\ntitle: 数学\ndraft: false\ntags: [math]\n---\n$x$", encoding="utf-8")
    assert cli.main(["create", str(article), "--dry-run"]) == 0
    root = parse_xml(capsys.readouterr().out.encode())
    assert root.findtext("app:control/app:draft", namespaces=NS) == "yes"
    assert root.findtext("a:title", namespaces=NS) == "数学"
    assert root.findtext("a:content", namespaces=NS) == "[$ x $]"
    assert root.find("a:category", NS).get("term") == "math"


def test_explicit_publish_and_title_override(tmp_path, capsys):
    article = tmp_path / "article.md"
    article.write_text("---\ntitle: old\n---\n$x$", encoding="utf-8")
    assert cli.main(["create", str(article), "--title", "new", "--publish", "--dry-run"]) == 0
    root = parse_xml(capsys.readouterr().out.encode())
    assert root.findtext("a:title", namespaces=NS) == "new"
    assert root.findtext("app:control/app:draft", namespaces=NS) == "no"


def test_convert_stdin(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("---\ntitle: x\n---\n$x$"))
    assert cli.main(["convert", "-", "--strip-front-matter"]) == 0
    assert capsys.readouterr().out == "[$ x $]"


def test_convert_file_preserves_front_matter(tmp_path):
    source = tmp_path / "in.md"
    target = tmp_path / "out.md"
    source.write_text("---\ntitle: '$a$'\n---\n$x$", encoding="utf-8")
    assert cli.main(["convert", str(source), "-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "---\ntitle: '$a$'\n---\n[$ x $]"


def test_delete_requires_yes_before_credentials(capsys):
    assert cli.main(["delete", "123"]) == 1
    assert "--yes" in capsys.readouterr().err


class FakeClient:
    def __init__(self):
        self.writes = []

    def get(self, entry_id):
        assert entry_id == "123"
        return parse_xml(ENTRY)

    def update(self, entry_id, data):
        self.writes.append((entry_id, data))
        return {"id": entry_id}

    def delete(self, entry_id):
        self.writes.append((entry_id, None))


def test_update_reads_then_preserves_draft(monkeypatch, capsys):
    client = FakeClient()
    monkeypatch.setattr(cli, "make_client", lambda args: client)
    assert cli.main(["update", "123", "--title", "new"]) == 0
    root = parse_xml(client.writes[0][1])
    assert root.findtext("app:control/app:draft", namespaces=NS) == "yes"
    assert root.findtext("a:content", namespaces=NS) == "$x$"


def test_update_dry_run_never_writes(monkeypatch, capsys):
    client = FakeClient()
    monkeypatch.setattr(cli, "make_client", lambda args: client)
    assert cli.main(["update", "123", "--publish", "--dry-run"]) == 0
    assert client.writes == []
    assert (
        parse_xml(capsys.readouterr().out.encode()).findtext("app:control/app:draft", namespaces=NS)
        == "no"
    )


def test_non_markdown_update_rejected(monkeypatch, tmp_path, capsys):
    client = FakeClient()
    monkeypatch.setattr(
        client, "get", lambda id: parse_xml(ENTRY.replace(b"text/x-markdown", b"text/html"))
    )
    monkeypatch.setattr(cli, "make_client", lambda args: client)
    source = tmp_path / "source.md"
    source.write_text("$x$", encoding="utf-8")
    assert cli.main(["update", "123", str(source)]) == 1
    assert client.writes == []
    assert "Markdown" in capsys.readouterr().err
    assert cli.main(["update", "123", str(source), "--no-convert"]) == 0


def test_delete_with_yes(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(cli, "make_client", lambda args: client)
    assert cli.main(["delete", "123", "--yes"]) == 0
    assert client.writes == [("123", None)]


@pytest.mark.parametrize(
    "args", [["update", "123"], ["convert", "missing-file.md"], ["auth", "login"]]
)
def test_handled_errors(args, capsys, monkeypatch):
    monkeypatch.setattr(cli.auth, "account", lambda user, blog: ("alice", "a.com"))
    assert cli.main(args) == 1
    assert "error:" in capsys.readouterr().err
