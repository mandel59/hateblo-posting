import pytest

from hateblo.errors import HatebloError
from hateblo.markdown import convert_math
from hateblo.tex import DELIMITER_PREFIXES


def convert(source, **kwargs):
    diagnostics = []
    result = convert_math(source, diagnostics=diagnostics, **kwargs)
    return result, diagnostics


def test_brackets_approximate_with_correct_atom_classes():
    result, findings = convert(r"$\llbracket x \rrbracket$")
    assert result == r"[$ \mathopen{[\![} x \mathclose{]\!]} $]"
    assert [finding.code for finding in findings] == ["MATH001", "MATH001"]
    assert [(finding.line, finding.column) for finding in findings] == [(1, 2), (1, 15)]
    assert all("近似" in finding.message for finding in findings)
    assert convert(result) == (result, [])


@pytest.mark.parametrize(
    "wrapper", ["${}$", "\\({}\\)", "$$\n{}\n$$", "\\[{}\\]", "```math\n{}\n```", "[$ {} $]"]
)
def test_all_math_forms(wrapper):
    result, findings = convert(wrapper.format(r"\llbracket x \rrbracket"))
    assert r"\mathopen{[\![}" in result
    assert r"\mathclose{]\!]}" in result
    assert len(findings) == 2


@pytest.mark.parametrize("prefix", sorted(DELIMITER_PREFIXES))
def test_sized_delimiters_not_corrupted(prefix):
    source = "$\\" + prefix + r" \llbracket x$"
    result, findings = convert(source)
    assert result == "[$ " + source[1:-1] + " $]"
    assert len(findings) == 1
    assert findings[0].code == "MATH002"
    assert "拡大区切り" in findings[0].message


def test_sizing_prefix_across_comment():
    result, findings = convert("$$\\left % comment\n\\llbracket x \\right\\rrbracket$$")
    assert r"\left \llbracket" in result
    assert [item.code for item in findings] == ["MATH002", "MATH002"]
    assert (findings[0].line, findings[0].column) == (2, 1)


def test_grouped_sizing_argument_not_rewritten():
    result, findings = convert(r"$\big{\llbracket}$")
    assert result == r"[$ \big{\llbracket} $]"
    assert findings[0].code == "MATH002"


def test_prefix_does_not_apply_across_other_content():
    result, findings = convert(r"$\left( x \llbracket y \rrbracket \right)$")
    assert r"\mathopen{[\![}" in result
    assert all(item.code == "MATH001" for item in findings)


def test_defined_macros_preserved():
    source = r"$\newcommand{\llbracket}{[}\llbracket x \rrbracket$"
    result, findings = convert(source)
    assert result == "[$ " + source[1:-1] + " $]"
    assert len(findings) == 3
    assert all(item.code == "MATH002" and "マクロ定義" in item.message for item in findings)


def test_official_migrations():
    result, findings = convert(r"$\bbFont{R} + \scr{F}$")
    assert result == r"[$ \mathbb{R} + \mathscr{F} $]"
    assert all("公式の移行先" in item.message for item in findings)


def test_control_sequence_boundaries_and_escaped_backslash():
    result, findings = convert(r"$\llbracketOther + \\rrbracket + \scrX$")
    assert result == r"[$ \llbracketOther + \\rrbracket + \scrX $]"
    assert findings == []


def test_comments_not_converted_or_reported():
    result, findings = convert("$$x % \\llbracket \\newcommand\n+\\rrbracket$$")
    assert r"\mathclose{]\!]}" in result
    assert len(findings) == 1
    assert (findings[0].line, findings[0].column) == (2, 2)


def test_code_prose_urls_and_html_remain_untouched():
    source = (
        "\\llbracket\n\n`$\\llbracket$`\n\n```tex\n$\\rrbracket$\n```\n\n<div>$\\llbracket$</div>\n"
    )
    assert convert(source) == (source, [])


def test_legacy_hatena_only_warns():
    source = r"[tex:\llbracket x \rrbracket]"
    result, findings = convert(source)
    assert result == source
    assert all(item.code == "MATH002" and "旧[tex:" in item.message for item in findings)


def test_off_keeps_commands_but_converts_math_delimiters():
    result, findings = convert(r"$\llbracket x \rrbracket$", math_compat="off")
    assert result == r"[$ \llbracket x \rrbracket $]"
    assert findings == []


def test_strict_reports_all_before_raising():
    findings = []
    with pytest.raises(HatebloError, match="2件"):
        convert_math(r"$\llbracket x \rrbracket$", math_compat="strict", diagnostics=findings)
    assert len(findings) == 2


def test_unknown_command_not_claimed_to_be_validated():
    assert convert(r"$\NotInTheRules{x}$", math_compat="strict") == (r"[$ \NotInTheRules{x} $]", [])


def test_library_warns_without_explicit_collector():
    with pytest.warns(UserWarning, match="MATH001"):
        convert_math(r"$\llbracket$")


def test_locations_sorted_even_when_fences_processed_first():
    source = "$\\llbracket$\n\n   ```math\n   \\rrbracket\n   ```\n\n$`\\scr{X}`$\n"
    _, findings = convert(source)
    assert [(item.line, item.column) for item in findings] == [(1, 2), (4, 4), (7, 3)]
