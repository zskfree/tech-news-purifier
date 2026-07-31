from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

Category = Literal["ai", "opensource", "systems"]
Decision = Literal["keep", "discard"]
VALID_CATEGORIES = {"ai", "opensource", "systems"}
VALID_DECISIONS = {"keep", "discard"}


@dataclass(frozen=True, slots=True)
class Article:
    article_id: str
    source: str
    title: str
    link: str
    summary: str


@dataclass(frozen=True, slots=True)
class PurificationResult:
    decision: Decision
    category: Category
    quality_score: int
    summary: str
    reason: str
    model_used: str = ""

    @classmethod
    def from_text(cls, text: str, *, model_used: str = "") -> PurificationResult:
        cleaned = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.I)
        if fenced:
            cleaned = fenced.group(1)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("AI 返回值必须是 JSON 对象")
        decision = str(data.get("decision", "")).lower()
        category = str(data.get("category", "")).lower()
        score = data.get("quality_score")
        summary = data.get("summary")
        reason = data.get("reason")
        if decision not in VALID_DECISIONS:
            raise ValueError("decision 必须为 keep 或 discard")
        if category not in VALID_CATEGORIES:
            raise ValueError("category 必须为 ai、opensource 或 systems")
        if not isinstance(score, int) or not 0 <= score <= 10:
            raise ValueError("quality_score 必须是 0 到 10 的整数")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary 不能为空")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason 不能为空")
        return cls(
            decision=decision,  # type: ignore[arg-type]
            category=category,  # type: ignore[arg-type]
            quality_score=score,
            summary=summary.strip(),
            reason=reason.strip(),
            model_used=model_used,
        )


@dataclass(frozen=True, slots=True)
class KeptArticle:
    source: str
    title: str
    link: str
    summary: str
    reason: str
    category: Category
    quality_score: int
    created_at: str


@dataclass(slots=True)
class ScriptSegment:
    title: str
    text: str
    category: Category | None = None
    audio_path: str | None = None
    duration_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class EditorialSection:
    category: Category
    title: str
    news_titles: tuple[str, ...]
    key_facts: tuple[str, ...]
    transition: str


@dataclass(frozen=True, slots=True)
class EditorialPlan:
    episode_theme: str
    intro_points: tuple[str, ...]
    sections: tuple[EditorialSection, ...]
    terminology: tuple[tuple[str, str], ...]
    outro_points: tuple[str, ...]

    @classmethod
    def from_text(cls, text: str) -> EditorialPlan:
        cleaned = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.I)
        if fenced:
            cleaned = fenced.group(1)
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("编辑提纲必须是 JSON 对象")

        theme = data.get("episode_theme")
        intro = data.get("intro_points")
        raw_sections = data.get("sections")
        terminology = data.get("terminology", {})
        outro = data.get("outro_points")
        if not isinstance(theme, str) or not theme.strip():
            raise ValueError("episode_theme 不能为空")
        if not isinstance(intro, list) or not intro or not all(isinstance(x, str) for x in intro):
            raise ValueError("intro_points 必须是非空字符串数组")
        if not isinstance(outro, list) or not outro or not all(isinstance(x, str) for x in outro):
            raise ValueError("outro_points 必须是非空字符串数组")
        if not isinstance(terminology, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in terminology.items()
        ):
            raise ValueError("terminology 必须是字符串映射")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValueError("sections 不能为空")

        sections: list[EditorialSection] = []
        seen_categories: set[str] = set()
        for raw in raw_sections:
            if not isinstance(raw, dict):
                raise ValueError("section 必须是 JSON 对象")
            category = str(raw.get("category", ""))
            title = raw.get("title")
            news_titles = raw.get("news_titles")
            key_facts = raw.get("key_facts")
            transition = raw.get("transition")
            if category not in VALID_CATEGORIES or category in seen_categories:
                raise ValueError("section category 非法或重复")
            if not isinstance(title, str) or not title.strip():
                raise ValueError("section title 不能为空")
            if not isinstance(news_titles, list) or not news_titles or not all(
                isinstance(x, str) and x.strip() for x in news_titles
            ):
                raise ValueError("news_titles 必须是非空字符串数组")
            if not isinstance(key_facts, list) or not key_facts or not all(
                isinstance(x, str) and x.strip() for x in key_facts
            ):
                raise ValueError("key_facts 必须是非空字符串数组")
            if not isinstance(transition, str):
                raise ValueError("transition 必须是字符串")
            seen_categories.add(category)
            sections.append(
                EditorialSection(
                    category=category,  # type: ignore[arg-type]
                    title=title.strip(),
                    news_titles=tuple(x.strip() for x in news_titles),
                    key_facts=tuple(x.strip() for x in key_facts),
                    transition=transition.strip(),
                )
            )
        return cls(
            episode_theme=theme.strip(),
            intro_points=tuple(x.strip() for x in intro),
            sections=tuple(sections),
            terminology=tuple(sorted((k.strip(), v.strip()) for k, v in terminology.items())),
            outro_points=tuple(x.strip() for x in outro),
        )
