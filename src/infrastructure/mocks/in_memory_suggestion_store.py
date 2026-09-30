import asyncio
from copy import deepcopy

from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import CommitteeScrutiny, SecretariatScrutiny, SuggestionStatus


def build_default_suggestions() -> list[Suggestion]:
    """Factory generating fresh, unlinked domain entity instances for mock seed data.

    Returns 6 realistic Persian suggestions across key operational statuses:
    - 2 EXECUTED (اجرا شده)
    - 2 APPROVED (مصوب)
    - 2 PENDING (در حال اجرا / در دست بررسی)
    """
    return [
        Suggestion(
            id="sug-101",
            content=SuggestionContent(
                title="بهینه‌سازی سیستم خنک‌کاری ترانسفورماتورهای قدرت",
                problem="افزایش دمای سیم‌پیچ‌های ترانسفورماتور در اوج بار تابستان و کاهش طول عمر عایقی",
                solution="نصب سیستم مه‌پاش هوشمند اتوماتیک با کنترل برخط دما و رطوبت محیط",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.EXECUTED,
                scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                description="طرح در پست ۴۰۰ کیلوولت شهید رجایی اجرا شده و کاهش دمای ۱۵ درجه‌ای ثبت گردید.",
            ),
            date=ShamsiDate("1402/03/10"),
            context_title="معاونت انتقال و تجارت خارجی",
            secretariat_evaluation=SecretariatEvaluation(
                scrutiny=SecretariatScrutiny.SEND_TO_APPROVER,
                comment="بررسی اولیه فنی انجام و مورد تایید است.",
            ),
            version=1,
            is_deleted=False,
        ),
        Suggestion(
            id="sug-102",
            content=SuggestionContent(
                title="طرح بازچرخانی پساب صنعتی برج‌های خنک‌کننده نیروگاه",
                problem="مصرف بالای آب خام در برج‌های خنک‌کننده نیروگاه‌های حرارتی و هزینه‌های تامین آب",
                solution="استفاده از سیستم فیلتراسیون اسمز معکوس دیسکی جهت تصفیه و بازچرخانی پساب",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.EXECUTED,
                scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                description="به صورت پایلوت در نیروگاه ری پیاده‌سازی و مصرف آب خام ۴۰ درصد کاهش یافت.",
            ),
            date=ShamsiDate("1402/05/20"),
            context_title="شرکت مادرتخصصی تولید نیروی برق حرارتی",
            version=1,
            is_deleted=False,
        ),
        Suggestion(
            id="sug-201",
            content=SuggestionContent(
                title="پیاده‌سازی کنتورهای هوشمند طرح فهام در شهرک‌های صنعتی",
                problem="عدم امکان مدیریت و پایش برخط مصرف برق صنایع در ایام اوج بار و کمبود دیسپاچینگ محلی",
                solution="تجهیز تمامی مشترکان دیماندی به مودم‌های قرائت از دور و قطع و وصل خودکار بار",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.APPROVED,
                scrutiny=CommitteeScrutiny.APPROVED,
                description="مصوب کمیته راهبری؛ ابلاغ به شرکت‌های توزیع نیروی برق جهت تخصیص بودجه و اجرا.",
            ),
            date=ShamsiDate("1402/08/15"),
            context_title="معاونت هماهنگی توزیع",
            version=1,
            is_deleted=False,
        ),
        Suggestion(
            id="sug-202",
            content=SuggestionContent(
                title="اتوماسیون و مانیتورینگ سکسیونرهای گازی شبکه فشار متوسط",
                problem="طولانی بودن زمان بازیابی شبکه در حوادث ناشی از شرایط جوی و خطای مانور دستی",
                solution="نصب RTU خورشیدی و کنترل از راه دور روی سکسیونرهای هوایی خطوط توزیع",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.APPROVED,
                scrutiny=CommitteeScrutiny.APPROVED,
                description="طرح تصویب شد و در فاز اول ۱۰۰ دستگاه سکسیونر در استان البرز در حال خرید تجهیزات است.",
            ),
            date=ShamsiDate("1402/10/05"),
            context_title="شرکت توزیع نیروی برق استان البرز",
            version=1,
            is_deleted=False,
        ),
        Suggestion(
            id="sug-301",
            content=SuggestionContent(
                title="استفاده از پهپادهای حرارتی برای پایش خطوط انتقال فوق توزیع",
                problem="خطرات جانی صعود کارگران و خطای دید انسانی در بازدیدهای سنتی خطوط صعب‌العبور",
                solution="به‌کارگیری پهپاد خودران مجهز به دوربین ترموویژن و پردازش تصویر با هوش مصنوعی",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.PENDING,
                scrutiny=CommitteeScrutiny.AWAITING_REVIEW,
                description="در دست بررسی کارگروه خطوط گرم؛ نیازمند ارزیابی پروتکل‌های پدافند غیرعامل.",
            ),
            date=ShamsiDate("1403/01/25"),
            context_title="شرکت برق منطقه‌ای تهران",
            version=1,
            is_deleted=False,
        ),
        Suggestion(
            id="sug-302",
            content=SuggestionContent(
                title="به‌کارگیری ترانسفورماتورهای فوق کم‌تلفات آمورف در مناطق گرمسیری",
                problem="تلفات بی‌باری بالای ترانسفورماتورهای سنتی در شرایط دمای بالا و رطوبت زیاد",
                solution="جایگزینی ترانس‌های هسته سیلیکونی با هسته فلزی آمورف در شرکت‌های توزیع جنوب کشور",
            ),
            evaluation=CommitteeEvaluation(
                status=SuggestionStatus.PENDING,
                scrutiny=CommitteeScrutiny.AWAITING_REVIEW,
                description="در مرحله ارزیابی فنی و اقتصادی بازگشت سرمایه در کارگروه استاندارد تجهیزات.",
            ),
            date=ShamsiDate("1403/02/18"),
            context_title="معاونت تحقیقات و منابع انسانی",
            version=1,
            is_deleted=False,
        ),
    ]


class InMemorySuggestionStore:
    """Thread-safe and process-local in-memory repository for Suggestion domain entities.

    Guarantees:
    - Thread safety via asyncio.Lock.
    - Deep-copy isolation on initialization and reset to prevent test mutations from contaminating seeds.
    - Full CRUD and soft-deletion operations matching SQL repository semantics.
    """

    def __init__(self, seed_suggestions: list[Suggestion] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._items: dict[str, Suggestion] = {}
        seeds = (
            seed_suggestions
            if seed_suggestions is not None
            else build_default_suggestions()
        )
        for s in seeds:
            self._items[s.id] = deepcopy(s)

    async def get(
        self, suggestion_id: str, include_deleted: bool = False
    ) -> Suggestion | None:
        """Fetch suggestion by ID. Returns None if absent or soft-deleted unless include_deleted=True."""
        async with self._lock:
            suggestion = self._items.get(suggestion_id)
            if suggestion is None:
                return None
            if suggestion.is_deleted and not include_deleted:
                return None
            return deepcopy(suggestion)

    async def exists(self, suggestion_id: str, include_deleted: bool = False) -> bool:
        """Check if suggestion exists in store."""
        async with self._lock:
            suggestion = self._items.get(suggestion_id)
            if suggestion is None:
                return False
            if suggestion.is_deleted and not include_deleted:
                return False
            return True

    async def upsert(self, suggestion: Suggestion) -> None:
        """Insert or replace suggestion in store."""
        async with self._lock:
            self._items[suggestion.id] = deepcopy(suggestion)

    async def soft_delete(self, suggestion_id: str) -> bool:
        """Mark suggestion as soft-deleted. Returns True if deleted, False if not found or already deleted."""
        async with self._lock:
            suggestion = self._items.get(suggestion_id)
            if suggestion is None or suggestion.is_deleted:
                return False
            suggestion.mark_deleted()
            suggestion.increment_version()
            return True

    async def list_active(self) -> list[Suggestion]:
        """Return all active (non-deleted) suggestions."""
        async with self._lock:
            return [deepcopy(s) for s in self._items.values() if not s.is_deleted]

    async def reset(self) -> int:
        """Reset store state back to initial 6 seed suggestions. Returns number of seeded items."""
        async with self._lock:
            self._items.clear()
            fresh_seeds = build_default_suggestions()
            for s in fresh_seeds:
                self._items[s.id] = deepcopy(s)
            return len(self._items)
