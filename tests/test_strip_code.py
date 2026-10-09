from app.core.llm import strip_code


def test_plain_code_unchanged():
    assert strip_code("  x = 1\n") == "x = 1"


def test_fenced_block():
    assert strip_code("```python\nx = 1\ny = 2\n```") == "x = 1\ny = 2"


def test_text_before_fence():
    # B30：Qwen 在代码块前加了 markdown 标题，旧实现原样 exec → SyntaxError
    assert strip_code("# 产品A在华北的记录\n\n```python\nx = 1\n```\n说明文字") == "x = 1"


def test_longest_of_several_blocks():
    assert strip_code("```\na = 1\n```\n然后\n```python\nb = 2\nc = 3\n```") == "b = 2\nc = 3"


def test_unclosed_fence():
    assert strip_code("```python\nx = 1") == "x = 1"
