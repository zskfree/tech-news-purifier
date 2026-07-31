import pytest

from tech_news_purifier.models import PurificationResult


def test_structured_result_accepts_valid_json() -> None:
    result = PurificationResult.from_text(
        '{"decision":"keep","category":"ai","quality_score":8,"summary":"摘要","reason":"理由"}',
        model_used="test",
    )
    assert result.decision == "keep"
    assert result.category == "ai"
    assert result.model_used == "test"


@pytest.mark.parametrize(
    "payload",
    [
        "DISCARD",
        '{"decision":"maybe","category":"ai","quality_score":8,"summary":"a","reason":"b"}',
        '{"decision":"keep","category":"other","quality_score":8,"summary":"a","reason":"b"}',
        '{"decision":"keep","category":"ai","quality_score":11,"summary":"a","reason":"b"}',
    ],
)
def test_structured_result_rejects_invalid_output(payload: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        PurificationResult.from_text(payload)
