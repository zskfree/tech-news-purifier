from tech_news_purifier.editorial import local_quality_issues, select_episode_articles
from tech_news_purifier.models import EditorialPlan, KeptArticle, ScriptSegment


def article(
    title: str, category: str, score: int, source: str = "Lobsters 极客社区"
) -> KeptArticle:
    return KeptArticle(
        source=source,
        title=title,
        link=f"https://example.com/{title}",
        summary="事实摘要",
        reason="关注原因",
        category=category,  # type: ignore[arg-type]
        quality_score=score,
        created_at="2026-07-31 07:00:00",
    )


def test_selection_filters_low_quality_caps_total_and_category() -> None:
    candidates = [article(f"AI-{i}", "ai", 10 - i % 3) for i in range(7)]
    candidates += [article(f"OSS-{i}", "opensource", 9) for i in range(3)]
    candidates += [article("weak", "systems", 6)]
    selected = select_episode_articles(candidates, min_score=7, limit=10)
    assert len(selected) <= 10
    assert all(item.quality_score >= 7 for item in selected)
    assert sum(item.category == "ai" for item in selected) == 4
    assert sum(item.category == "opensource" for item in selected) == 3
    assert all(item.title != "weak" for item in selected)


def test_editorial_plan_requires_unique_valid_sections() -> None:
    plan = EditorialPlan.from_text(
        """{
          "episode_theme":"模型效率与工程落地",
          "intro_points":["模型更新"],
          "sections":[{
            "category":"ai","title":"模型进展","news_titles":["新闻A"],
            "key_facts":["发布了新版本"],"transition":"接着看工程影响"
          }],
          "terminology":{"LLM":"大语言模型"},
          "outro_points":["更新范围有限"]
        }"""
    )
    assert plan.sections[0].news_titles == ("新闻A",)
    assert dict(plan.terminology)["LLM"] == "大语言模型"


def test_local_quality_gate_finds_promotional_and_repeated_paragraphs() -> None:
    repeated = "这段文字包含足够长的事实说明，用于验证相邻段落重复检测能够稳定触发。"
    segments = [
        ScriptSegment("开场", f"史诗级更新。\n{repeated}\n{repeated}"),
        ScriptSegment("结尾", "本期结论到这里。"),
    ]
    issues = local_quality_issues(segments)
    assert any("宣传性语言" in issue for issue in issues)
    assert any("相邻段落重复" in issue for issue in issues)
