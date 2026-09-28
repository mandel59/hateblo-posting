"""Source-preserving conversion to Hatena's native, unescaped [$ ... $] math."""

import re
import warnings

from markdown_it import MarkdownIt

from .errors import HatebloError
from .tex import Compatibility, MathDiagnostic

PROTECTED_INLINE = re.compile(
    r"\[\$[\s\S]*?\$\]|\[tex:[^\n]*?\]|<!--(?:[\s\S]*?)-->"
    r"|<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>"
)
BACKTICKS = re.compile(r"`+")


def _escaped(text: str, index: int) -> bool:
    start = index
    while start > 0 and text[start - 1] == "\\":
        start -= 1
    return (index - start) % 2 == 1


def _render(body: str, display: bool, compatibility: Compatibility, offset: int) -> str:
    body = compatibility.rewrite(body, offset)
    # Folding lines must not turn a TeX comment into a comment on the entire expression.
    lines = []
    for line in body.splitlines():
        for index, char in enumerate(line):
            if char == "%" and not _escaped(line, index):
                line = line[:index]
                break
        lines.append(line.strip())
    tex = " ".join(lines).strip()
    if not tex:
        raise HatebloError("空の数式があります。数式を記入するか区切りをエスケープしてください。")
    if "$]" in tex:
        raise HatebloError("数式中の $] ははてなの数式終了記号と衝突します。")
    if display:
        return "[$ \\displaystyle " + tex + " $]"
    return "[$ " + tex + " $]"


def _convert_text(text: str, dollar_math: bool, compatibility: Compatibility, offset: int) -> str:
    result = []
    index = 0
    while index < len(text):
        # Preserve existing Hatena syntax, inline code and HTML (including attributes).
        protected = PROTECTED_INLINE.match(text, index)
        if protected:
            original = protected[0]
            if original.startswith("[$"):
                original = "[$" + compatibility.rewrite(original[2:-2], offset + index + 2) + "$]"
            elif original.startswith("[tex:"):
                compatibility.rewrite(original[5:-1], offset + index + 5, legacy=True)
            result.append(original)
            index += len(protected[0])
            continue
        if text[index] == "`" and not _escaped(text, index):
            run = BACKTICKS.match(text, index)[0]
            end = re.compile(r"(?<!`)" + re.escape(run) + r"(?!`)").search(text, index + len(run))
            if end:
                stop = end.end()
                result.append(text[index:stop])
                index = stop
                continue
        # Link destinations and reference definitions are not prose.
        if text.startswith("](", index):
            depth, stop = 1, index + 2
            while stop < len(text) and depth:
                if not _escaped(text, stop):
                    depth += (text[stop] == "(") - (text[stop] == ")")
                stop += 1
            result.append(text[index:stop])
            index = stop
            continue
        opener = None
        for candidate in ("$$", "$", r"\[", r"\(") if dollar_math else (r"\[", r"\("):
            if text.startswith(candidate, index) and not _escaped(text, index):
                opener = candidate
                break
        if opener:
            closer = {r"\[": r"\]", r"\(": r"\)"}.get(opener, opener)
            start = index + len(opener)
            display = opener in ("$$", r"\[")
            end = start
            while True:
                end = text.find(closer, end)
                if end < 0:
                    break
                body = text[start:end]
                valid = not _escaped(text, end) and bool(body.strip())
                if not display:
                    if "\n" in body:
                        end = -1
                        break
                github_math = (
                    opener == "$"
                    and body.startswith("`")
                    and body.endswith("`")
                    and body.count("`") == 2
                )
                # A stray currency dollar must not consume a later code span or link.
                if not github_math and any(
                    char == "`" and not _escaped(body, position)
                    for position, char in enumerate(body)
                ):
                    valid = False
                if "](" in body or "[$" in text[start : end + len(closer)]:
                    valid = False
                if opener == "$":
                    valid = (
                        valid
                        and not body[0].isspace()
                        and not body[-1].isspace()
                        and not body.startswith("$")
                        and (end + 1 == len(text) or not text[end + 1].isdigit())
                    )
                if valid:
                    if github_math:
                        body = body[1:-1]  # GitHub's $`...`$ inline form.
                    result.append(
                        _render(body, display, compatibility, offset + start + github_math)
                    )
                    index = end + len(closer)
                    break
                end += len(closer)
            if end >= 0:
                continue
            if opener != "$":
                raise HatebloError("閉じられていない数式があります: " + opener)
        result.append(text[index])
        index += 1
    return "".join(result)


def convert_math(
    source: str,
    *,
    dollar_math: bool = True,
    math_compat: str = "warn",
    diagnostics: list[MathDiagnostic] | None = None,
) -> str:
    """Convert math; collect compatibility findings or emit Python warnings.

    Strict mode reports all findings and raises before returning any output.
    This recognizes known compatibility rules, not arbitrary unsupported TeX.
    """
    if math_compat not in {"off", "warn", "strict"}:
        raise ValueError("math_compat must be off, warn or strict")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    compatibility = Compatibility(source, math_compat != "off")
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    protected = []
    for token in MarkdownIt("commonmark").parse(source):
        if token.type in {"fence", "code_block", "html_block"} and token.map:
            start, end = token.map
            replacement = source[offsets[start] : offsets[end]]
            if token.type == "fence" and token.info.strip() == "math" and token.level == 0:
                closing = lines[end - 1].strip()
                if not re.fullmatch(
                    re.escape(token.markup[0]) + "{" + str(len(token.markup)) + ",}", closing
                ):
                    raise HatebloError("閉じられていない math コードフェンスがあります。")
                # Use original source for precise positions (including up to 3-space indent).
                body = "".join(lines[start + 1 : end - 1])
                replacement = _render(body, True, compatibility, offsets[start + 1]) + "\n"
            protected.append((offsets[start], offsets[end], replacement))
    # Markdown reference links are not exposed as tokens by markdown-it.
    for match in re.finditer(r"(?m)^ {0,3}\[[^\]\n]+\]:[^\n]*(?:\n|$)", source):
        protected.append((match.start(), match.end(), match[0]))
    result, cursor = [], 0
    for start, end, replacement in sorted(protected):
        if start < cursor:
            continue
        result.append(_convert_text(source[cursor:start], dollar_math, compatibility, cursor))
        result.append(replacement)
        cursor = end
    result.append(_convert_text(source[cursor:], dollar_math, compatibility, cursor))
    findings = sorted(compatibility.diagnostics, key=lambda item: (item.line, item.column))
    if diagnostics is not None:
        diagnostics.extend(findings)
    elif math_compat == "warn":
        for finding in findings:
            warnings.warn(finding.format(), stacklevel=2)
    if math_compat == "strict" and findings:
        details = "\n".join(finding.format() for finding in findings) if diagnostics is None else ""
        raise HatebloError(
            f"数式互換性の診断が{len(findings)}件あります。strictモードで停止しました。"
            + ("\n" + details if details else "")
        )
    return "".join(result)
