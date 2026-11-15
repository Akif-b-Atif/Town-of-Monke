from monke.adapter.textutil import rel, clock, split_text, chunked


def test_rel_clock():
    assert rel(1700000000.9) == "<t:1700000000:R>"
    assert clock(1700000000) == "<t:1700000000:t>"


def test_short_text_untouched():
    assert split_text("hello", 2000) == ["hello"]
    assert split_text("", 2000) == []


def test_split_at_lines_and_limit():
    text = "\n".join(["x" * 10] * 10)
    parts = split_text(text, 30)
    assert all(len(p) <= 30 for p in parts)
    assert "\n".join(parts) == text


def test_long_line_hard_split():
    parts = split_text("y" * 95, 40)
    assert [len(p) for p in parts] == [40, 40, 15]


def test_chunked():
    assert [len(c) for c in chunked(list(range(23)), 10)] == [10, 10, 3]