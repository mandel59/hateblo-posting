import pytest

from hateblo.document import parse_document
from hateblo.errors import HatebloError
from hateblo.markdown import convert_math


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("日本語 $x_i^2$ です。", "日本語 [$ x_i^2 $] です。"),
        (r"\(a < b & c\)", "[$ a < b & c $]"),
        (r"\[x_i^2\]", r"[$ \displaystyle x_i^2 $]"),
        ("$$\nx^2\n$$\n", "[$ \\displaystyle x^2 $]\n"),
        ("```math\nx_i\n```\n", "[$ \\displaystyle x_i $]\n"),
        ("~~~math\nx_i\n~~~~\n", "[$ \\displaystyle x_i $]\n"),
        ("$`x_i`$", "[$ x_i $]"),
        ("$x$ and $y$", "[$ x $] and [$ y $]"),
        ("$$a % comment\n+b$$", r"[$ \displaystyle a +b $]"),
        (r"$a\%b$", r"[$ a\%b $]"),
        (
            "\\[\\begin{aligned}\na &= b \\\\\nc &= d\n\\end{aligned}\\]",
            r"[$ \displaystyle \begin{aligned} a &= b \\ c &= d \end{aligned} $]",
        ),
        ("- $x$\n\n> $y$\n", "- [$ x $]\n\n> [$ y $]\n"),
        ("| 値 |\n| --- |\n| $x$ |\n", "| 値 |\n| --- |\n| [$ x $] |\n"),
        ("[数式 $x$](https://example.test/$y$)", "[数式 [$ x $]](https://example.test/$y$)"),
    ],
)
def test_conversion(source, expected):
    assert convert_math(source) == expected
    assert convert_math(expected) == expected


@pytest.mark.parametrize(
    "source",
    [
        "```python\ntext = '$x$'\n```\n",
        "~~~\n$x$\n~~~\n",
        "    $x$\n",
        "`$x$` and `` `$y$` ``",
        "`code\n$x$`",
        "[$ x_i $] and [tex:x_i]",
        r"\$x\$",
        "$5 and $10",
        "$ x $",
        "$unclosed",
        "<pre>\n$x$\n</pre>\n",
        '<a href="https://example.test/$x$">link</a>',
        "[link](https://example.test/a($x$))",
        "[ref]: https://example.test/$x$\n",
        "> ```\n> $x$\n> ```\n",
        "- code:\n\n      $x$\n",
        "```\n$x$",  # CommonMark allows unclosed ordinary code fences.
        "Price $5; code `$x$`.",
        "Price $5; [link](https://example.test/$x$).",
        "Price $5; [$ x $].",
    ],
)
def test_preservation(source):
    assert convert_math(source) == source


@pytest.mark.parametrize("source", ["$$x", r"\(x", r"\[x", "```math\nx\n", "$$ % empty\n$$"])
def test_invalid_math(source):
    with pytest.raises(HatebloError):
        convert_math(source)


def test_no_dollar_math():
    assert convert_math(r"$x$ $$y$$ \(z\)", dollar_math=False) == "$x$ $$y$$ [$ z $]"


def test_currency_before_code_does_not_swallow_following_math():
    assert convert_math("Price $5; `$x$`; $y$.") == "Price $5; `$x$`; [$ y $]."


@pytest.mark.parametrize("value", ["false", "0", "[]", "text"])
def test_front_matter_scalar_or_empty_list_rejected(value):
    with pytest.raises(HatebloError):
        parse_document(f"---\n{value}\n---\nbody")


def test_front_matter_preserved_and_typed():
    source = "---\ntitle: '$title$'\ncategories: [数学]\n---\n$x$\n"
    document = parse_document(source)
    assert document.metadata == {"title": "$title$", "categories": ["数学"]}
    assert document.front_matter + document.body == source
    assert convert_math(document.body) == "[$ x $]\n"


@pytest.mark.parametrize(
    "source",
    [
        "---\ntitle: missing close",
        "---\n- list\n---\n",
        "---\ntitle: 123\n---\n",
        "---\ncategories: string\n---\n",
        "---\ntitle: [\n---\n",
        "---\na: !!python/object/apply:os.system [echo]\n---\n",
    ],
)
def test_invalid_front_matter(source):
    with pytest.raises(HatebloError):
        parse_document(source)
