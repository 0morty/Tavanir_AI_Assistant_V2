from dataclasses import dataclass

from src.domain.entities import Reference


@dataclass(frozen=True)
class SimilarSuggestionReference(Reference):
    """Reference metadata describing a retrieved similar suggestion.

    Carries the suggestion identity, review status, specialized domain, and
    the raw reranker relevance logit.
    """

    suggestion_id: str
    status: str
    similarity: float
    context_title: str | None = None

    @property
    def description(self) -> str:
        """Domain description providing LLM intuition about the reference fields."""
        return (
            "ارجاع به سابقه یک پیشنهاد مشابه در سامانه نظام پیشنهادات توانیر. "
            "ویژگی similarity امتیاز لاجیت خام (Raw Logit) خروجی از مدل بازرتبه‌بندی "
            "(Cross-Encoder Reranker) بدون اعمال تابع سیگموئید (Sigmoid) است. "
            "مستندات با امتیاز کمتر از صفر پیش‌تر فیلتر شده‌اند؛ بنابراین مقادیر مثبت "
            "نشان‌دهنده میزان انطباق و ارتباط معنایی و فنی پیشنهاد بازیابی‌شده با پیشنهاد جاری است."
        )
