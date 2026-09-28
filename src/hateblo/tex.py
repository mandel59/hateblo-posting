"""Small, evidence-based compatibility rules; this is not a TeX validator."""

import re
from bisect import bisect_right
from dataclasses import dataclass

TOKEN = re.compile(r"%[^\n]*|\\(?:[A-Za-z]+|[^\n])")
REPLACEMENTS = {
    "llbracket": r"\mathopen{[\![}",
    "rrbracket": r"\mathclose{]\!]}",
    "bbFont": r"\mathbb",
    "scr": r"\mathscr",
}
DELIMITER_PREFIXES = {
    "left",
    "right",
    "middle",
    "big",
    "Big",
    "bigg",
    "Bigg",
    "bigl",
    "Bigl",
    "biggl",
    "Biggl",
    "bigr",
    "Bigr",
    "biggr",
    "Biggr",
    "bigm",
    "Bigm",
    "biggm",
    "Biggm",
}
DEFINITIONS = {
    "def",
    "gdef",
    "edef",
    "xdef",
    "let",
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareMathOperator",
    "newenvironment",
    "renewenvironment",
}


@dataclass(frozen=True)
class MathDiagnostic:
    code: str
    line: int
    column: int
    command: str
    message: str

    def format(self, filename: str = "<input>", line_offset: int = 0) -> str:
        return (
            f"{filename}:{self.line + line_offset}:{self.column}: "
            f"warning[{self.code}]: {self.command}: {self.message}"
        )


class Compatibility:
    def __init__(self, source: str, enabled: bool):
        self.enabled = enabled
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.diagnostics: list[MathDiagnostic] = []

    def report(self, offset: int, command: str, code: str, message: str) -> None:
        line = bisect_right(self.line_starts, offset)
        column = offset - self.line_starts[line - 1] + 1
        self.diagnostics.append(MathDiagnostic(code, line, column, command, message))

    def rewrite(self, body: str, offset: int, *, legacy: bool = False) -> str:
        if not self.enabled:
            return body
        # Control symbols (including \\ and \%) are consumed as whole tokens.
        tokens = [match for match in TOKEN.finditer(body) if not match[0].startswith("%")]
        defined = any(match[0][1:] in DEFINITIONS for match in tokens)
        result, cursor = [], 0
        for index, match in enumerate(tokens):
            name = match[0][1:]
            if name not in REPLACEMENTS:
                continue
            previous = tokens[index - 1] if index else None
            gap = body[previous.end() : match.start()] if previous else ""
            gap = re.sub(r"%[^\n]*", "", gap).strip()
            sized = (
                previous is not None
                and previous[0][1:] in DELIMITER_PREFIXES
                and re.fullmatch(r"[\s{]*", gap) is not None
            )
            replacement = REPLACEMENTS[name]
            if legacy or defined or sized:
                reason = (
                    "旧[tex:…]記法はエスケープの解釈が異なるため"
                    if legacy
                    else "マクロ定義を含む数式のため"
                    if defined
                    else "拡大区切りの直後では単純置換できないため"
                )
                self.report(
                    offset + match.start(),
                    match[0],
                    "MATH002",
                    reason + "変換しません。数式を手動で確認してください。",
                )
                continue
            approximate = name in {"llbracket", "rrbracket"}
            message = (
                f"{replacement} に近似変換しました。括弧の形・間隔を確認してください。"
                if approximate
                else f"公式の移行先 {replacement} に変換しました。"
            )
            self.report(offset + match.start(), match[0], "MATH001", message)
            result.extend((body[cursor : match.start()], replacement))
            cursor = match.end()
        result.append(body[cursor:])
        return "".join(result)
