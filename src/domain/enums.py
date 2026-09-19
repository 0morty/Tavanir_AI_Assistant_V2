from enum import Enum

from src.domain.exceptions import (
    InvalidCommitteeScrutinyError,
    InvalidSecretariatScrutinyError,
    InvalidSuggestionStatusError,
)


class HistoryRole(Enum):
    """Sender role of a history message, OpenAI-compatible for chat history."""

    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"


class SuggestionStatus(Enum):
    NOT_ACCEPTED = ("عدم پذیرش", 1)
    REJECTED = ("رد", 2)
    APPROVED = ("مصوب", 3)
    PENDING = ("در حال اجرا", 4)
    EXECUTED = ("اجرا شده", 5)

    def __init__(self, title_fa: str, status_id: int):
        self.title_fa = title_fa
        self.status_id = status_id

    @classmethod
    def from_string(cls, value: str) -> "SuggestionStatus":
        """Find status by Persian title."""
        for item in cls:
            if item.title_fa == value or item.name == value:
                return item
        raise InvalidSuggestionStatusError(
            f"Unknown suggestion status string: '{value}'"
        )

    @classmethod
    def from_id(cls, status_id: int) -> "SuggestionStatus":
        """Find status by status_id integer."""
        for item in cls:
            if item.status_id == status_id:
                return item
        raise InvalidSuggestionStatusError(f"Unknown suggestion status ID: {status_id}")


def _normalize_enum_lookup_text(val: str) -> str:
    """Helper to normalize Persian text for resilient enum matching."""
    return (
        val.strip()
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .replace("  ", " ")
    )


class SecretariatScrutiny(Enum):
    SEND_TO_APPROVER = (-2, "ارسال به تایید کننده")
    EXPERT_OPINION = (-1, "اظهار نظر تخصصی")
    OUT_OF_FRAMEWORK = (0, "خارج از چهارچوب")
    GENERAL_CONDITIONS_NOT_MET = (1, "عدم احراز شرایط عمومی پذیرش")
    REFER_TO_EXPERT = (2, "ارجاع به کارشناسی")
    REFER_TO_COMMITTEE = (3, "ارجاع به کمیته")
    ALREADY_SUBMITTED_BY_PERSON = (4, "این پیشنهاد قبلا توسط شخصی ارائه شده است")
    ALREADY_SUBMITTED_BY_NUMBER = (5, "این پیشنهاد قبلا طی شماره ای ارائه شده است")
    DUPLICATE = (6, "این پیشنهاد تکراری است و قبلا ارائه شده است")
    RETURNED_FOR_COMPLETION = (7, "برگشت به پیشنهاددهنده جهت تکمیل")
    NOT_A_SUGGESTION = (8, "مورد طرح شده به دلایل ذیل پیشنهاد محسوب نمی شود")
    REJECTED = (9, "به دلایل ذیل پیشنهاد ارائه شده رد می باشد")
    SEND_TO_EXPERT_GROUP = (15, "ارسال به گروه کارشناسی")
    REFER_TO_ANOTHER_SECRETARIAT = (16, "ارجاع به دبیرخانه دیگر")
    AUTO_REJECTED_EXPERT = (17, "رد خودکار به دلیل کارشناسی")

    def __init__(self, code: int, title_fa: str):
        self.code = code
        self.title_fa = title_fa

    @classmethod
    def from_code(cls, code: int) -> "SecretariatScrutiny":
        for item in cls:
            if item.code == code:
                return item
        raise InvalidSecretariatScrutinyError(
            f"Unknown secretariat scrutiny code: {code}"
        )

    @classmethod
    def from_string(cls, value: str) -> "SecretariatScrutiny":
        norm = _normalize_enum_lookup_text(value)
        for item in cls:
            if (
                _normalize_enum_lookup_text(item.title_fa) == norm
                or item.name == value.strip()
            ):
                return item
        raise InvalidSecretariatScrutinyError(
            f"Unknown secretariat scrutiny string: '{value}'"
        )

    @property
    def is_duplicate(self) -> bool:
        return self.code in (4, 5, 6)

    @property
    def is_rejection(self) -> bool:
        return self.code in (0, 1, 8, 9, 17)


class CommitteeScrutiny(Enum):
    SELECT_CONSULTANT_RETURN_FOR_CORRECTION = (-10, "انتخاب مشاور و برگشت جهت اصلاح")
    REJECTED_EXPERT_OPINION = (-9, "رد به دلیل رد کارشناسی")
    SEND_FOR_EXPERT_OPINION = (-8, "ارسال جهت اظهار نظر تخصصی")
    PILOT_EXECUTION = (-7, "اجرای پایلوت")
    OUT_OF_FRAMEWORK_REGULATION = (-6, "خارج از چارچوب ایین نامه نظام پیشنهاد ها")
    GENERAL_CONDITIONS_NOT_MET = (-5, "عدم احراز شرایط عمومی پذیرش")
    GENERALIZE_EXECUTION = (-4, "تعمیم اجرا")
    APPROVED_PRELIMINARY = (-3, "تایید")
    SEND_TO_UPPER_SECRETARIAT_COMMITTEE = (-2, "ارسال به کمیته دبیرخانه بالادستی")
    INVITE_TO_SESSION = (-1, "دعوت به جلسه")
    APPROVED = (0, "تایید")
    REJECTED = (1, "رد")
    SEND_TO_EXPERT = (2, "ارسال به کارشناس")
    RETURN_FOR_CORRECTION = (3, "برگشت جهت اصلاح")
    AWAITING_REVIEW = (4, "منتظر بررسی")
    ACCEPTED_AS_IDEA = (5, "پذیرفته شده به عنوان ایده")
    ACCEPTED_AS_EXECUTED_SUGGESTION = (6, "پذیرفته شده به عنوان پیشنهاد اجراشده")
    RETURN_TO_SECRETARIAT_CHANGE_COMMITTEE = (7, "عودت به دبیرخانه جهت تغییر کمیته")
    SEND_TO_EXPERT_GROUP = (8, "ارسال به گروه کارشناسی")
    ADMINISTRATIVE_OR_PERSONAL_REQUEST = (
        9,
        "درخواستهای اداری و یا ملزومات شخصی می باشد .",
    )
    BEYOND_AUTHORITY_CONTRARY_TO_POLICIES = (
        10,
        "خارج از حدود اختیارات و مغایر با سیاستها ، قوانین و اساسنامه شرکت",
    )
    NO_METHOD_OR_ADVANTAGES_SPECIFIED = (
        11,
        "ارائه پیشنهاد بدون اعلام روش پیشنهادی و مزایای آن",
    )
    DUPLICATE_FROM_OTHER_PERSON = (
        12,
        "قبلا از سوی پیشنهاد دهنده دیگر اعلام شده است . ( پیشنهاد  تکراری )",
    )
    CRITIQUE_OR_REMINDER_ONLY = (
        13,
        "جنبه تذکر ، یادآوری و انتقاد از روش و استاندارد انجام کار است",
    )
    WITHIN_ROUTINE_DUTIES = (14, "در حد وظایف جاری شرکت است")
    EXECUTION_COST_EXCEEDS_BENEFITS = (15, "هزینه اجرایی آن بیش از فوائد اجرای آن است")
    PLANNED_IN_FUTURE_PROGRAMS = (
        16,
        "در برنامه های آتی شرکت به صورت مستند پیش بینی شده است",
    )
    CURRENTLY_UNDERWAY = (17, "در حال انجام است")
    NOT_FEASIBLE = (18, "غیر قابل اجرا میباشد")
    NOT_BENEFICIAL_FOR_COMPANY = (19, "به صرفه و صلاح شرکت نیست")
    IS_A_COMPLAINT = (20, "طرح شکایت است")
    ON_COMPANY_AGENDA = (21, "در دستور کار شرکت است")

    def __init__(self, code: int, title_fa: str):
        self.code = code
        self.title_fa = title_fa

    @classmethod
    def from_code(cls, code: int) -> "CommitteeScrutiny":
        for item in cls:
            if item.code == code:
                return item
        raise InvalidCommitteeScrutinyError(f"Unknown committee scrutiny code: {code}")

    @classmethod
    def from_string(cls, value: str) -> "CommitteeScrutiny":
        norm = _normalize_enum_lookup_text(value)
        # Disambiguation: "تایید" maps to modern code 0 (APPROVED) per architectural decision
        if norm == _normalize_enum_lookup_text("تایید"):
            return cls.APPROVED
        for item in cls:
            if (
                _normalize_enum_lookup_text(item.title_fa) == norm
                or item.name == value.strip()
            ):
                return item
        raise InvalidCommitteeScrutinyError(
            f"Unknown committee scrutiny string: '{value}'"
        )


class SuggestionChunkType(str, Enum):
    TITLE = "title"
    PROBLEM = "problem"
    SOLUTION = "solution"
    EVALUATION = "evaluation"


class SourceType(Enum):
    SUGGESTION = ("suggestion", 1)
    STATUTE = ("statute", 2)


class ChunkStatus(str, Enum):
    ACTIVE = "active"
    STAGING = "staging"
    DEPRECATED = "deprecated"


class RegulatoryDocumentType(str, Enum):
    STATUTE = "statute"  # قانون
    REGULATION = "regulation"  # آیین‌نامه
    DIRECTIVE = "directive"  # بخشنامه
    PROCEDURE = "procedure"  # دستورالعمل
    GUIDELINE = "guideline"  # شیوه‌نامه / راهنما


class AuthorityLevel(str, Enum):
    BINDING = "binding"  # الزامی
    GUIDANCE = "guidance"  # ارشادی / توصیه‌ای
