import pytest

from tech_news_purifier.audio import clean_tts_text, split_text, validate_duration


def test_split_text_honours_max_length_for_long_sentence() -> None:
    chunks = split_text("甲" * 605, max_length=280)
    assert "".join(chunks) == "甲" * 605
    assert max(map(len, chunks)) <= 280


def test_clean_tts_text_removes_markup_and_urls_slashes() -> None:
    assert clean_tts_text("<b>你好</b> **世界**") == "你好 世界"


def test_duration_boundaries_are_inclusive() -> None:
    assert validate_duration(1080, 1080, 1320) == 1080
    assert validate_duration(1320, 1080, 1320) == 1320
    with pytest.raises(ValueError):
        validate_duration(1079.99, 1080, 1320)
    with pytest.raises(ValueError):
        validate_duration(1320.01, 1080, 1320)
