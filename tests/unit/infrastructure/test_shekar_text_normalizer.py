import pytest
from src.application.interfaces.i_text_normalizer import ITextNormalizer

from src.application.exceptions import TextNormalizationError
from src.domain.entities import ShamsiDate
from src.infrastructure.services.text_processing.shekar_text_normalizer import (
    ShekarTextNormalizer,
)


@pytest.fixture
def normalizer() -> ShekarTextNormalizer:
    return ShekarTextNormalizer()


def test_normalizer_implements_interface(normalizer: ShekarTextNormalizer):
    assert isinstance(normalizer, ITextNormalizer)


def test_arabic_to_persian_character_normalization(normalizer: ShekarTextNormalizer):
    # Arabic Kaf (ك U+0643) -> Persian Ke (ک U+06A9)
    # Arabic Yeh (ي U+064A) -> Persian Ye (ی U+06CC)
    raw_text = "كتاب عربي و پيگيري"
    normalized = normalizer.normalize(raw_text)

    assert "ك" not in normalized
    assert "ي" not in normalized
    assert "کتاب" in normalized
    assert "عربی" in normalized
    assert "پیگیری" in normalized


def test_emoji_and_diacritic_removal(normalizer: ShekarTextNormalizer):
    raw_text = "پیشنهاد عالی! 💡🚀 مَتْنِ با اِعْراب"
    normalized = normalizer.normalize(raw_text)

    assert "💡" not in normalized
    assert "🚀" not in normalized
    assert "َ" not in normalized
    assert "ِ" not in normalized
    assert "متن با اعراب" in normalized


def test_persian_and_arabic_digits_to_ascii(normalizer: ShekarTextNormalizer):
    raw_text = "شماره ثبت ۱۲۳۴۵ و کد رهگیری ٦٧٨٩٠"
    normalized = normalizer.normalize(raw_text)

    assert "12345" in normalized
    assert "67890" in normalized
    assert "۱۲۳۴۵" not in normalized
    assert "٦٧٨٩٠" not in normalized


def test_shamsi_date_compatibility(normalizer: ShekarTextNormalizer):
    raw_date = "تاریخ: ۱۴۰۲/۰۵/۱۵"
    normalized = normalizer.normalize(raw_date)

    assert "1402/05/15" in normalized
    # Extract date string and verify ShamsiDate entity accepts it without error
    date_str = "1402/05/15"
    shamsi_date = ShamsiDate(value=date_str)
    assert str(shamsi_date) == date_str


def test_url_preservation(normalizer: ShekarTextNormalizer):
    raw_text = (
        "سامانه توانیر در آدرس https://tavanir.org.ir/portal/home?id=123 در دسترس است."
    )
    normalized = normalizer.normalize(raw_text)

    assert "https://tavanir.org.ir/portal/home?id=123" in normalized
    assert "https: //" not in normalized


def test_markdown_table_divider_preservation(normalizer: ShekarTextNormalizer):
    raw_table = """
| ستون اول | ستون دوم | ستون سوم |
| :--- | :---: | ---: |
| داده ۱ | داده ۲ | داده ۳ |
"""
    normalized = normalizer.normalize(raw_table)

    assert "| :--- | :---: | ---: |" in normalized
    assert "| -- |" not in normalized
    assert "داده 1" in normalized


def test_empty_and_whitespace_handling(normalizer: ShekarTextNormalizer):
    assert normalizer.normalize("") == ""
    assert normalizer.normalize_batch([]) == []


def test_batch_normalization(normalizer: ShekarTextNormalizer):
    inputs = ["كتاب ۱", "پيشنهاد ۲", "قانون ۳"]
    results = normalizer.normalize_batch(inputs)

    assert len(results) == 3
    assert results[0] == "کتاب 1"
    assert results[1] == "پیشنهاد 2"
    assert results[2] == "قانون 3"


@pytest.mark.asyncio
async def test_async_parity(normalizer: ShekarTextNormalizer):
    raw_text = "كتاب عربي با کد ۱۲۳ 💡"
    sync_result = normalizer.normalize(raw_text)
    async_result = await normalizer.normalize_async(raw_text)

    assert async_result == sync_result
    assert async_result == "کتاب عربی با کد 123"

    batch_sync = normalizer.normalize_batch([raw_text, "شماره ٤٥٦"])
    batch_async = await normalizer.normalize_batch_async([raw_text, "شماره ٤٥٦"])

    assert batch_async == batch_sync


def test_error_handling_wraps_in_text_normalization_error(
    monkeypatch, normalizer: ShekarTextNormalizer
):
    def faulty_transform(_):
        raise RuntimeError("Low-level tokenizer crash")

    monkeypatch.setattr(normalizer._normalizer, "fit_transform", faulty_transform)

    with pytest.raises(TextNormalizationError) as exc_info:
        normalizer.normalize("متن تست")

    assert "Failed to normalize Persian text" in str(exc_info.value)


# ==============================================================================
# Markdown Architecture & Syntax Preservation Tests
# ==============================================================================


def test_markdown_heading_hierarchy_preservation(normalizer: ShekarTextNormalizer):
    """
    Verifies that ATX headings (# to ######) maintain their exact marker count
    and are not collapsed by RepeatedLetterNormalizer (e.g., '###' must NOT become '##').
    Also verifies that Persian text following the marker is properly normalized.
    """
    raw_headings = """# فصل اول: كليات ۱
## بخش دوم: تعاريف و ارجاعات
### ماده ۳: شرايط عمومي پيمان
#### بند الف: ضوابط اجرايي
##### جزء ۱: مشخصات فني
###### تبصره ۱: موارد خاص
"""
    normalized = normalizer.normalize(raw_headings)

    assert "# فصل اول: کلیات 1\n" in normalized
    assert "## بخش دوم: تعاریف و ارجاعات\n" in normalized
    assert "### ماده 3: شرایط عمومی پیمان\n" in normalized
    assert "#### بند الف: ضوابط اجرایی\n" in normalized
    assert "##### جزء 1: مشخصات فنی\n" in normalized
    assert "###### تبصره 1: موارد خاص" in normalized

    # Critical boundary checks: ensure heading counts did not degrade
    lines = [line for line in normalized.splitlines() if line.strip()]
    assert lines[0].startswith("# ")
    assert lines[1].startswith("## ")
    assert lines[2].startswith("### ")
    assert lines[3].startswith("#### ")
    assert lines[4].startswith("##### ")
    assert lines[5].startswith("###### ")


def test_markdown_fenced_code_blocks_verbatim(normalizer: ShekarTextNormalizer):
    """
    Verifies that fenced code blocks (``` or ~~~) remain 100% byte-for-byte identical,
    preserving indentation, newlines, commas, brackets, quotes, and language tags.
    """
    raw_text = """متن قبل از كد:

```python
def calculate_tariff(kwh: float, rate_code: str = "T1") -> float:
    # Persian digits like ۱۲۳ in code comments or constants must NOT be modified
    rates = {
        "T1": [0.5, 1.2],
        "T2": [1.8, 2.5],
    }
    return kwh * rates[rate_code][0]
```

متن بعد از كد."""

    normalized = normalizer.normalize(raw_text)

    # Surrounding Persian text is normalized
    assert "متن قبل از کد:" in normalized
    assert "متن بعد از کد." in normalized

    # Code block is preserved verbatim
    expected_code = """```python
def calculate_tariff(kwh: float, rate_code: str = "T1") -> float:
    # Persian digits like ۱۲۳ in code comments or constants must NOT be modified
    rates = {
        "T1": [0.5, 1.2],
        "T2": [1.8, 2.5],
    }
    return kwh * rates[rate_code][0]
```"""
    assert expected_code in normalized


def test_markdown_inline_code_preservation(normalizer: ShekarTextNormalizer):
    """
    Verifies that inline code spans (`...`) preserve backticks and content
    without stripping backticks or translating commas/quotes.
    """
    raw_text = (
        "دستور `pip install shekar==1.6.3` و مقدار `timeout_sec = 30` را بررسي كنيد."
    )
    normalized = normalizer.normalize(raw_text)

    assert "`pip install shekar==1.6.3`" in normalized
    assert "`timeout_sec = 30`" in normalized
    assert "را بررسی کنید." in normalized


def test_markdown_links_and_images_preservation(normalizer: ShekarTextNormalizer):
    """
    Verifies that:
    1. Markdown links [anchor](url) do NOT have spaces inserted between ']' and '('.
    2. Markdown images ![alt](url) do NOT have spaces inserted after '!' or between ']' and '('.
    3. Anchor and alt texts are normalized for Persian spelling and digits.
    4. Target URLs (relative, absolute, anchor fragments, queries) are untouched.
    """
    raw_text = (
        "جهت ثبت‌نام به [درگاه ملي توانير ۱۴۰۲](https://tavanir.org.ir/portal?id=۱۲۳&lang=fa) "
        "يا [آيين‌نامه اجرايي](#article-14) مراجعه كنيد.\n"
        "![لوگوي رسمي شركت](assets/images/logo_v2.png)"
    )
    normalized = normalizer.normalize(raw_text)

    # Must NOT have space between ']' and '('
    assert (
        "[درگاه ملی توانیر 1402](https://tavanir.org.ir/portal?id=۱۲۳&lang=fa)"
        in normalized
    )
    assert "[آیین‌نامه اجرایی](#article-14)" in normalized
    assert "] (" not in normalized

    # Must NOT have space between '!' and '[' or between ']' and '('
    assert "![لوگوی رسمی شرکت](assets/images/logo_v2.png)" in normalized
    assert "! [" not in normalized


def test_markdown_task_lists_preservation(normalizer: ShekarTextNormalizer):
    """
    Verifies that task list checkboxes (- [ ] and - [x]) are preserved
    and not collapsed into '- []' by spacing normalizers.
    """
    raw_text = """- [ ] اقدام اول: بررسي پيشنهاد
- [x] اقدام دوم: تاييد مدارك
* [ ] اقدام سوم: ارسال به كارگروه
* [x] اقدام چهارم: ثبت نهايي"""

    normalized = normalizer.normalize(raw_text)

    assert "- [ ] اقدام اول: بررسی پیشنهاد" in normalized
    assert "- [x] اقدام دوم: تایید مدارک" in normalized
    assert "* [ ] اقدام سوم: ارسال به کارگروه" in normalized
    assert "* [x] اقدام چهارم: ثبت نهایی" in normalized
    assert "- []" not in normalized
    assert "* []" not in normalized


def test_markdown_blockquotes_and_alerts_preservation(
    normalizer: ShekarTextNormalizer,
):
    """
    Verifies that single (>) and nested (>>) blockquotes, as well as GitHub
    alert callouts (> [!NOTE], > [!IMPORTANT]), maintain their syntax.
    """
    raw_text = """> [!IMPORTANT]
> رعايت مفاد اين دستورالعمل الزامي است.
>> تبصره داخلي: مرجع رسيدگي كميسيون عالي است."""

    normalized = normalizer.normalize(raw_text)

    assert "> [!IMPORTANT]" in normalized
    assert "> رعایت مفاد این دستورالعمل الزامی است." in normalized
    assert ">> تبصره داخلی: مرجع رسیدگی کمیسیون عالی است." in normalized


def test_markdown_nested_list_indentation_preservation(
    normalizer: ShekarTextNormalizer,
):
    """
    Verifies that multi-space indentations (2 spaces, 4 spaces) for nested
    unordered and ordered lists are preserved and not collapsed to 1 space.
    """
    raw_text = """* فهرست اصلي:
  - زيرمورد اول با ۲ فاصله
    * زير-زيرمورد با ۴ فاصله
1. گام اول
   1. زيرگام با ۳ فاصله"""

    normalized = normalizer.normalize(raw_text)

    assert "* فهرست اصلی:\n" in normalized
    assert "  - زیرمورد اول با 2 فاصله\n" in normalized
    assert "    * زیر-زیرمورد با 4 فاصله\n" in normalized
    assert "1. گام اول\n" in normalized
    assert "   1. زیرگام با 3 فاصله" in normalized


def test_markdown_horizontal_rules_preservation(normalizer: ShekarTextNormalizer):
    """
    Verifies that horizontal rules (---, ***, ___) are NOT collapsed
    to two characters (-- or **) by RepeatedLetterNormalizer.
    """
    raw_text = """بخش اول
---
بخش دوم
***
بخش سوم
___
پایان"""

    normalized = normalizer.normalize(raw_text)

    assert "\n---\n" in normalized
    assert "\n***\n" in normalized
    assert "\n___\n" in normalized


def test_markdown_table_structure_and_alignment_preservation(
    normalizer: ShekarTextNormalizer,
):
    """
    Verifies that complete Markdown tables with header, divider row with
    colons (:---, :---:, ---:), and cell pipes remain valid Markdown while
    normalizing cell contents.
    """
    raw_table = """| شماره | نام پيشنهاد | وضعيت | امتياز |
| :--- | :---: | ---: | :--- |
| ۱ | بهينه‌سازي شبكه | در حال بررسي | ۱۸.۵ |
| ۲ | هوشمندسازي كنتورها | تصويب شده | ۱۹.۷۵ |"""

    normalized = normalizer.normalize(raw_table)

    assert "| شماره | نام پیشنهاد | وضعیت | امتیاز |" in normalized
    assert "| :--- | :---: | ---: | :--- |" in normalized
    assert "| 1 | بهینه‌سازی شبکه | در حال بررسی | 18.5 |" in normalized
    assert "| 2 | هوشمندسازی کنتورها | تصویب شده | 19.75 |" in normalized


def test_markdown_math_and_latex_preservation(normalizer: ShekarTextNormalizer):
    """
    Verifies that inline math ($...$) and block math ($$...$$) expressions
    are preserved without stripping '$' or modifying mathematical notation.
    """
    raw_text = (
        "فرمول ضريب تعديل $E = mc^2$ است و رابطه كلي:\n$$\\sum_{i=1}^n x_i = 100$$"
    )
    normalized = normalizer.normalize(raw_text)

    assert "$E = mc^2$" in normalized
    assert "$$\\sum_{i=1}^n x_i = 100$$" in normalized


def test_markdown_bold_and_italic_syntax_preservation(
    normalizer: ShekarTextNormalizer,
):
    """
    Verifies that bold (**), italic (*), and triple bold-italic (***)
    syntax is preserved without delimiter collapse or unwanted whitespace
    before closing delimiters after sentence-ending punctuation.
    """
    raw_text = (
        "این متن **کاملاً پررنگ** و این متن *مایل* است.\n"
        "***تذکر بسیار مهم: رعایت ضوابط الزامی است.***"
    )
    normalized = normalizer.normalize(raw_text)

    assert "**کاملا پررنگ**" in normalized
    assert "*مایل*" in normalized
    # Triple asterisks must not be collapsed to double
    assert "***تذکر بسیار مهم: رعایت ضوابط الزامی است.***" in normalized


def test_realistic_document_markdown_architecture_preservation(
    normalizer: ShekarTextNormalizer,
):
    """
    End-to-end integration test with a complete legal regulatory document
    containing all Markdown architecture elements combined together.
    """
    document = """# آيين‌نامه نظام پيشنهادهاي شركت توانير

> [!IMPORTANT]
> رعايت كليه مفاد اين آيين‌نامه براي شركت‌هاي زيرمجموعه الزامي است.

## فصل اول: كليات و تعاريف

### ماده ۱: دامنه كاربرد
اين آيين‌نامه بر اساس مصوبه شماره ۱۴۰۲/۵۶۷ هيئت وزيران تصويب شده است.
جهت ثبت اطلاعات به سامانه https://tavanir.org.ir مراجعه نموده يا از [پورتال خدمات](https://setadiran.ir/portal?id=99) استفاده نماييد.
![فرآيند ارزيابي](docs/flowchart.png)

### ماده ۲: جدول حد نصاب مالي
حد نصاب مالي پيشنهادها طبق جدول زير محاسبه مي‌گردد:

| رديف | طبقه معامله | ضريب تعديل | سقف ريالي (ميليارد) |
| :--- | :--- | :---: | ---: |
| ۱ | كوچك | ۰.۸۵ | ۱.۴۵ |
| ۲ | متوسط | ۱.۰۰ | ۱۴.۵۰ |
| ۳ | بزرگ | ۱.۲۵ | بيش از ۱۴.۵۰ |

---

### ماده ۳: فرمول فني و نمونه كد
فرمول امتيازدهي به صورت $Score = \\alpha \\times 100$ و ضريب $\\alpha = 0.85$ مي‌باشد.
نمونه اسكريپت استعلام:

```python
def check_status(suggestion_id: int) -> dict:
    # Persian digits like ۱۲۳ in code comments must stay untouched
    return {"id": suggestion_id, "status": "APPROVED", "rate": [0.5, 1.2]}
```

پارامتر `timeout_sec = 60` و شناسه `suggestion_id` الزامي است.

#### تبصره ۱: چك‌ليست اقدامات اوليه
- [ ] بررسي انطباق با اسناد بالادستي
- [x] تاييد هويت در سامانه ثبت احوال
  * بررسي عدم تعارض منافع
    - استعلام سازمان بازرسي
  * استعلام كد ملي و شناسه سازماني

***تذكر نهايي: هرگونه پرداخت منوط به تاييد كميسيون تخصصي است.***
"""

    normalized = normalizer.normalize(document)

    # 1. Zero token leakage
    assert "_TAVANIR_TOKEN_" not in normalized

    # 2. Heading hierarchy intact
    assert "# آیین‌نامه نظام پیشنهادهای شرکت توانیر" in normalized
    assert "## فصل اول: کلیات و تعاریف" in normalized
    assert "### ماده 1: دامنه کاربرد" in normalized
    assert "### ماده 2: جدول حدنصاب مالی" in normalized
    assert "### ماده 3: فرمول فنی و نمونه کد" in normalized
    assert "#### تبصره 1: چک‌لیست اقدامات اولیه" in normalized

    # 3. Callout and blockquotes intact
    assert "> [!IMPORTANT]" in normalized
    assert (
        "> رعایت کلیه مفاد این آیین‌نامه برای شرکت‌های زیرمجموعه الزامی است."
        in normalized
    )

    # 4. Links and images intact
    assert "https://tavanir.org.ir" in normalized
    assert "[پورتال خدمات](https://setadiran.ir/portal?id=99)" in normalized
    assert "![فرآیند ارزیابی](docs/flowchart.png)" in normalized

    # 5. Table intact with decimal numbers
    assert "| ردیف | طبقه معامله | ضریب تعدیل | سقف ریالی (میلیارد) |" in normalized
    assert "| :--- | :--- | :---: | ---: |" in normalized
    assert "| 1 | کوچک | 0.85 | 1.45 |" in normalized
    assert "| 2 | متوسط | 1.00 | 14.50 |" in normalized

    # 6. Horizontal rule intact
    assert "\n---\n" in normalized

    # 7. Math expressions intact
    assert "$Score = \\alpha \\times 100$" in normalized
    assert "$\\alpha = 0.85$" in normalized

    # 8. Fenced code block intact verbatim
    assert "def check_status(suggestion_id: int) -> dict:" in normalized
    assert (
        "# Persian digits like ۱۲۳ in code comments must stay untouched" in normalized
    )
    assert (
        '{"id": suggestion_id, "status": "APPROVED", "rate": [0.5, 1.2]}' in normalized
    )

    # 9. Inline code intact
    assert "`timeout_sec = 60`" in normalized
    assert "`suggestion_id`" in normalized

    # 10. Task list checkboxes and nested list indentation intact
    assert "- [ ] بررسی انطباق با اسناد بالادستی" in normalized
    assert "- [x] تایید هویت در سامانه ثبت احوال" in normalized
    assert "  * بررسی عدم تعارض منافع" in normalized
    assert "    - استعلام سازمان بازرسی" in normalized

    # 11. Bold-italic with punctuation intact
    assert (
        "***تذکر نهایی: هرگونه پرداخت منوط به تایید کمیسیون تخصصی است.***" in normalized
    )


def test_literal_placeholder_and_protected_code_collision_prevention(
    normalizer: ShekarTextNormalizer,
):
    """
    ING-17: Verifies that literal placeholder strings like '_TAVANIR_TOKEN_0_'
    in the raw text are not corrupted or replaced when neighboring code spans
    are masked and restored.
    """
    raw_text = "مصرف انرژی _TAVANIR_TOKEN_0_ و `x = ۱`"
    normalized = normalizer.normalize(raw_text)

    # Both literal string and code block must be preserved independently
    assert "_TAVANIR_TOKEN_0_" in normalized
    assert "`x = ۱`" in normalized
    assert normalized == "مصرف انرژی _TAVANIR_TOKEN_0_ و `x = ۱`"

