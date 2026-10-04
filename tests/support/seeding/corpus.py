"""Curated RAG golden benchmark seed corpus for Tavanir AI Assistant V2 tests.

Provides strongly-typed domain instances for:
- 20 employee suggestions covering 5 semantic clusters with cross-status representation,
  multi-chunk essays, empty vs rich committee commentary, and soft deletion.
- 10 regulatory documents / statutes (RegulatoryChunk instances with binding/advisory
  statuses, statutes, directives, and procedures).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities import (
    Chunk,
    ChunkStatus,
    CommitteeEvaluation,
    RegulatoryChunk,
    RegulatoryChunkMetadata,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import (
    AuthorityLevel,
    CommitteeScrutiny,
    RegulatoryDocumentType,
    SecretariatScrutiny,
    SuggestionStatus,
)

# ---------------------------------------------------------------------------
# Semantic Clusters
# ---------------------------------------------------------------------------
CLUSTER_DISTRIBUTION = "distribution_transformers"
CLUSTER_METERING = "smart_metering"
CLUSTER_RENEWABLE = "renewable_solar"
CLUSTER_TRANSMISSION = "transmission_protection"
CLUSTER_CYBERSECURITY = "it_cybersecurity"

CLUSTERS = [
    CLUSTER_DISTRIBUTION,
    CLUSTER_METERING,
    CLUSTER_RENEWABLE,
    CLUSTER_TRANSMISSION,
    CLUSTER_CYBERSECURITY,
]

CLUSTER_TITLES_FA = {
    CLUSTER_DISTRIBUTION: "توزیع / ترانسفورماتورها",
    CLUSTER_METERING: "کنتورهای هوشمند / لوازم اندازه‌گیری و صورتحساب",
    CLUSTER_RENEWABLE: "انرژی‌های تجدیدپذیر / نیروگاه خورشیدی",
    CLUSTER_TRANSMISSION: "انتقال / رله و حفاظت پست‌ها",
    CLUSTER_CYBERSECURITY: "فناوری اطلاعات / امنیت سایبری سامانه‌ها",
}


@dataclass(frozen=True)
class ClusteredSuggestion:
    cluster: str
    suggestion: Suggestion


@dataclass(frozen=True)
class ClusteredRegulatoryChunk:
    cluster: str
    chunk: RegulatoryChunk


# ---------------------------------------------------------------------------
# Long Multi-Chunk Essay Texts
# ---------------------------------------------------------------------------
_LONG_PROBLEM_ESSAY = (
    "در حال حاضر در بخش قابل توجهی از شبکه‌های توزیع فشار ضعیف و متوسط کشور، ترانسفورماتورهای توزیع فاقد سامانه پایش "
    "برخط و هوشمند بار حرارتی و نقطه داغ سیم‌پیچ می‌باشند. این موضوع منجر به عدم آگاهی دیسپاچینگ و اکیپ‌های بهره‌برداری "
    "از اضافه بارهای مقطعی در ساعات اوج بار تابستان شده و شکست عایقی زودرس، سوختن ترانسفورماتور و تحمیل خاموشی‌های گسترده به "
    "مشترکین خانگی و صنعتی را در پی دارد. بررسی‌های آماری سال‌های اخیر نشان می‌دهد بیش از ۲۵ درصد از خرابی‌های ترانسفورماتورهای "
    "توزیع ناشی از عدم تعادل فازها و افزایش دمای هسته و روغن عایق بیش از حد استاندارد IEC 60076 است. "
    "\n\n"
    "علاوه بر این، در حال حاضر فرآیند نمونه‌برداری و آزمون‌های گازکروماتوگرافی (DGA) و شکست دی‌الکتریک روغن ترانسفورماتورها "
    "به صورت کاملاً سنتی، دستی و با فواصل زمانی طولانی (گاه بیش از یک سال یک‌بار) انجام می‌گیرد. این امر موجب می‌شود پدیده‌های "
    "تخلیه جزئی داخلی، پیرشدگی شدید کاغذ سلولزی و رطوبت‌زدگی مخزن تا زمان بروز اتصال کوتاه شدید و انهدام کامل ترانسفورماتور "
    "پنهان باقی بماند. هزینه‌های ناشی از جایگزینی ترانسفورماتورهای سوخته، روغن‌ریزی و آلودگی‌های زیست‌محیطی حاصل از آن، "
    "خسارات جبران‌ناپذیری به دارایی‌های فیزیکی شرکت‌های توزیع وارد می‌کند و ضرورت پایش مستمر را دوچندان می‌سازد. "
    "\n\n"
    "از سوی دیگر، نبود یک پایگاه داده متمرکز و یکپارچه برای ثبت شناسنامه فنی، تاریخچه بارگیری، ضریب تلفات بی‌باری و بارداری "
    "و نتایج آزمایش‌های دوره‌ای ترانسفورماتورها در سطح شرکت‌های توزیع استانی، اتخاذ راهبردهای نگهداری و تعمیرات پیشگیرانه (PM) "
    "و پیش‌بینانه (CBM) را ناممکن ساخته است. بنابراین تغییر پارادایم از تعمیرات واکنشی پس از خرابی به سمت مانیتورینگ بلادرنگ "
    "یکی از حیاتی‌ترین نیازهای زیرساختی شبکه توزیع نیروی برق کشور به شمار می‌رود."
)

_LONG_SOLUTION_ESSAY = (
    "طرح پیشنهادی شامل استقرار سامانه‌ای یکپارچه و هوشمند جهت پایش بلادرنگ پارامترهای الکتریکی، حرارتی و مکانیکی "
    "ترانسفورماتورهای توزیع با استفاده از حسگرهای IoT کم‌مصرف مبتنی بر بستر ارتباطی LoRaWAN یا مودم‌های سلولار NB-IoT می‌باشد. "
    "این سامانه از طریق نصب ترانسدیوسرهای جریان بدون تماس (روگوفسکی) بر روی بوشینگ‌ها، حسگرهای دمای سطحی مخزن و پراب غوطه‌ور "
    "در روغن بالایی (Top Oil Temperature)، پارامترهای جریان هر فاز، هارمونیک‌های جریان، ولتاژ، دمای روغن و تراز روغن را به صورت "
    "پیوسته ثبت و به سرور مرکزی مانیتورینگ مخابره می‌نماید. "
    "\n\n"
    "در سطح نرم‌افزار مرکزی، یک موتور تحلیلی مبتنی بر الگوریتم‌های هوش مصنوعی و یادگیری ماشین مستقر می‌گردد که بر مبنای مدل‌های "
    "حرارتی استاندارد IEEE Std C57.91، دمای نقطه داغ (Hot Spot) را لحظه به لحظه تخمین زده و نرخ فرسایش عایقی و عمر باقی‌مانده "
    "ترانسفورماتور را محاسبه می‌کند. همچنین با تحلیل امضاهای جریانی و طیف ارتعاشات هسته، نشانه‌های اولیه شل‌شدگی اتصالات مکانیکی، "
    "پدیده اشباع مغناطیسی هسته و پدیدار شدن جریان‌های هجومی مکرر به طور خودکار شناسایی شده و هشدارهای پیشگیرانه برای واحدهای عملیاتی صادر می‌شود. "
    "\n\n"
    "علاوه بر این، سامانه مذکور قابلیت ادغام کامل با سامانه‌های اطلاعات جغرافیایی (GIS) و اتوماسیون توزیع (DMS/SCADA) شرکت را داراست. "
    "با ارسال خودکار تیکت تعمیراتی در صورت عبور دما از آستانه مجاز (۸۵ درجه سانتی‌گراد) یا ناترازی بار فازها بیش از ۱۵ درصد، اکیپ‌های "
    "تعمیراتی بلافاصله به محل پست هدایت می‌شوند. با اجرای آزمایشی این طرح در ۵۰ دستگاه ترانسفورماتور پربار منطقه، نرخ حوادث تا "
    "۶۵ درصد کاهش و طول عمر مفید ترانسفورماتورها به میزان حداقل ۵ سال افزایش خواهد یافت."
)


# ---------------------------------------------------------------------------
# Corpus Suggestions (20 items across 5 clusters)
# ---------------------------------------------------------------------------
def _build_suggestions() -> list[ClusteredSuggestion]:
    items: list[ClusteredSuggestion] = []

    # =========================================================================
    # CLUSTER 1: Distribution / Grid Transformers (4 suggestions)
    # =========================================================================

    # 1. Multi-chunk essay, APPROVED, rich committee commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_DISTRIBUTION,
            suggestion=Suggestion(
                id="sugg-dist-001",
                content=SuggestionContent(
                    title="سامانه پایش برخط و جامع وضعیت بار حرارتی و روغن ترانسفورماتورهای توزیع با فناوری اینترنت اشیا",
                    problem=_LONG_PROBLEM_ESSAY,
                    solution=_LONG_SOLUTION_ESSAY,
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.APPROVED,
                    scrutiny=CommitteeScrutiny.APPROVED,
                    description=(
                        "طرح با نظر مثبت اعضای کمیته تخصصی توزیع مواجه گردید. نتایج تحلیل اقتصادی نشان داد استقرار "
                        "حسگرهای حرارتی اینترنت اشیا بر روی ترانسفورماتورهای بحرانی می‌تواند نرخ خاموشی ناخواسته را تا ۷۰ درصد کاهش دهد."
                    ),
                    scrutiny_id=0,
                ),
                date=ShamsiDate("1402/04/12"),
                context_title="شرکت توزیع نیروی برق تهران بزرگ",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
                    comment="مدارک فنی و استانداردهای پیشنهادی با راهبردهای تحول دیجیتال صنعت برق تطابق دارد.",
                    scrutiny_id=3,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 2. PENDING, moderate description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_DISTRIBUTION,
            suggestion=Suggestion(
                id="sugg-dist-002",
                content=SuggestionContent(
                    title="طرح بازپیکربندی خودکار فیدرهای فشار متوسط توزیع جهت متوازن‌سازی بار ترانسفورماتورهای فوق‌توزیع",
                    problem=(
                        "عدم توازن بار روی ترانسفورماتورهای پست‌های فوق‌توزیع در ساعات پیک شبکه موجب افت شدید ولتاژ "
                        "در انتهای خطوط و تلفات مضاعف مس و آهن در ترانسفورماتورها می‌گردد."
                    ),
                    solution=(
                        "استفاده از الگوریتم بهینه‌سازی ازدحام ذرات (PSO) در ترکیب با سکسیونرهای گازی موتوردار کنترل‌پذیر "
                        "از دیسپاچینگ جهت جابجایی بار بین فیدرهای مجاور و کاهش بار ترانسفورماتورهای بحرانی."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.PENDING,
                    scrutiny=CommitteeScrutiny.PILOT_EXECUTION,
                    description="تصویب جهت اجرای پایلوت در امور دیسپاچینگ و اتوماسیون منطقه شمال شرق.",
                    scrutiny_id=-7,
                ),
                date=ShamsiDate("1402/07/20"),
                context_title="شرکت توزیع نیروی برق مشهد",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.EXPERT_OPINION,
                    comment="نیازمند هماهنگی با زیرساخت اسکادای موجود شرکت می‌باشد.",
                    scrutiny_id=-1,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 3. REJECTED, empty/minimal description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_DISTRIBUTION,
            suggestion=Suggestion(
                id="sugg-dist-003",
                content=SuggestionContent(
                    title="استفاده از روغن‌های گیاهی خوراکی بازیافتی به عنوان خنک‌کننده در ترانسفورماتورهای توزیع هوایی",
                    problem=(
                        "روغن‌های معدنی ترانسفورماتور گران‌قیمت بوده و خطرات زیست‌محیطی اشتعال و آلودگی آب‌های زیرزمینی را دارند."
                    ),
                    solution=(
                        "جایگزینی روغن معدنی با روغن‌های گیاهی تصفیه شده محلی جهت خنک‌سازی سیم‌پیچ‌های ترانسفورماتورهای توزیع."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.REJECTED,
                    scrutiny=CommitteeScrutiny.BEYOND_AUTHORITY_CONTRARY_TO_POLICIES,
                    description=None,  # Empty evaluation edge case
                    scrutiny_id=10,
                ),
                date=ShamsiDate("1401/11/05"),
                context_title="شرکت توزیع نیروی برق شیراز",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REJECTED,
                    comment="مغایر با استانداردهای رسمی ایمنی و تست دی‌الکتریک توانیر.",
                    scrutiny_id=9,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 4. EXECUTED, rich description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_DISTRIBUTION,
            suggestion=Suggestion(
                id="sugg-dist-004",
                content=SuggestionContent(
                    title="تجهیز ترانسفورماتورهای توزیع به رله‌های مانیتورینگ گاز و ترمومترهای مغناطیسی بی‌سیم",
                    problem=(
                        "عدم ثبت سابقه افزایش دما و تولید گاز در ترانسفورماتورهای فاقد رله بوخهلتس سبب بروز حوادث ناگهانی انفجار بوشینگ می‌شود."
                    ),
                    solution=(
                        "نصب کیت‌های ماژولار ارزان‌قیمت سنجش فشار گاز و دمای روغن با قابلیت ارسال هشدار پیامکی به کشیک اتفاقات شبکه."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.EXECUTED,
                    scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                    description="طرح با موفقیت بر روی ۱۲۰ دستگاه ترانسفورماتور پرحادثه نصب و موجب پیشگیری از سوختن ۶ دستگاه گردید.",
                    scrutiny_id=6,
                ),
                date=ShamsiDate("1400/09/18"),
                context_title="شرکت توزیع نیروی برق اصفهان",
                secretariat_evaluation=None,
                is_deleted=False,
                version=2,
            ),
        )
    )

    # =========================================================================
    # CLUSTER 2: Smart Metering / Billing (4 suggestions)
    # =========================================================================

    # 5. APPROVED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_METERING,
            suggestion=Suggestion(
                id="sugg-meter-001",
                content=SuggestionContent(
                    title="پیاده‌سازی الگوریتم کشف دستکاری و سرقت انرژی در کنتورهای هوشمند طرح فهام با یادگیری ژرف",
                    problem=(
                        "دستکاری فیزیکی و مغناطیسی کنتورهای هوشمند و ایجاد خطای تعمدی در ترانس جریان (CT) موجب تلفات غیرفنی سنگین "
                        "در شبکه توزیع و کسری درآمد حاصل از فروش برق می‌گردد."
                    ),
                    solution=(
                        "طراحی مدل شبکه عصبی بازگشتی (LSTM) بر روی داده‌های سری زمانی توان راکتیو، ولتاژ و پروفایل بار دریافتی از سامانه MDM "
                        "جهت شناسایی ناهنجاری‌ها و انحرافات معنادار مصرف مشترکین صنعتی و دیماندی."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.APPROVED,
                    scrutiny=CommitteeScrutiny.APPROVED,
                    description="الگوریتم مورد تایید معاونت خدمات مشترکین قرار گرفت و دستور ادغام آن با سامانه فهام صادر شد.",
                    scrutiny_id=0,
                ),
                date=ShamsiDate("1402/05/14"),
                context_title="شرکت توزیع نیروی برق استان خوزستان",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
                    comment="مستندات اعتبارسنجی الگوریتم و کد نرم‌افزاری نمونه ضمیمه شده است.",
                    scrutiny_id=3,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 6. PENDING, moderate description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_METERING,
            suggestion=Suggestion(
                id="sugg-meter-002",
                content=SuggestionContent(
                    title="سامانه خودکار صدور قبوض دینامیک لحظه‌ای با تعرفه‌های پویای زمان مصرف (CPP) از طریق کنتورهای AMI",
                    problem=(
                        "تعرفه‌گذاری ثابت فعلی انگیزه کافی برای انتقال بار مصرفی مشترکین پرمصرف به ساعات کم‌باری شب ایجاد نمی‌کند."
                    ),
                    solution=(
                        "ارسال تعرفه لحظه‌ای پیک بحرانی (Critical Peak Pricing) بر بستر پروتکل DLMS/COSEM کنتورها و اپلیکیشن مشترکین "
                        "برای مدیریت خودکار لوازم برقی پرمصرف."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.PENDING,
                    scrutiny=CommitteeScrutiny.SEND_FOR_EXPERT_OPINION,
                    description="جهت بررسی حقوقی و تطبیق با مصوبات وزارت نیرو به دفتر مدیریت مصرف ارجاع شد.",
                    scrutiny_id=-8,
                ),
                date=ShamsiDate("1402/08/11"),
                context_title="شرکت توزیع نیروی برق تهران بزرگ",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 7. NOT_ACCEPTED, empty description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_METERING,
            suggestion=Suggestion(
                id="sugg-meter-003",
                content=SuggestionContent(
                    title="حذف کامل کنتورهای برق فیزیکی و جایگزینی با تخمین مصرف مشترک بر اساس مساحت اعیانی ملک",
                    problem=(
                        "هزینه خرید، کالیبراسیون و نصب کنتورهای هوشمند و اعزام مامورین قرائت بسیار بالا است."
                    ),
                    solution=(
                        "محاسبه قبض برق کلیه مشترکین خانگی صرفاً با ضرب متراژ ساختمان در یک ضریب ثابت فصلی بدون نیاز به ابزار اندازه‌گیری."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.NOT_ACCEPTED,
                    scrutiny=CommitteeScrutiny.GENERAL_CONDITIONS_NOT_MET,
                    description=None,  # Empty evaluation
                    scrutiny_id=-5,
                ),
                date=ShamsiDate("1401/03/25"),
                context_title="شرکت توزیع نیروی برق استان فارس",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.OUT_OF_FRAMEWORK,
                    comment="پیشنهاد خلاف قوانین مدنی و قانون سازمان برق ایران است.",
                    scrutiny_id=0,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 8. EXECUTED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_METERING,
            suggestion=Suggestion(
                id="sugg-meter-004",
                content=SuggestionContent(
                    title="مودم‌های قرائت از دور چندپروتکله جهت یکپارچه‌سازی کنتورهای نسل قدیم با شبکه ملی فهام",
                    problem=(
                        "تعداد زیادی کنتور الکترونیکی فاقد مودم داخلی در شبکه وجود دارد که تعویض آن‌ها هزینه هنگفتی دارد."
                    ),
                    solution=(
                        "طراحی و ساخت مودم رابط اکسترنال با پورت نوری و RS485 که پروتکل‌های IEC 62056 را به صورت استاندارد رمزنگاری و ارسال می‌کند."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.EXECUTED,
                    scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                    description="با تولید و نصب ۱۰ هزار دستگاه مودم بومی، بیش از ۵۰ میلیارد ریال در تعویض کنتورها صرفه‌جویی گردید.",
                    scrutiny_id=6,
                ),
                date=ShamsiDate("1400/06/30"),
                context_title="شرکت توزیع نیروی برق استان مرکزی",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # =========================================================================
    # CLUSTER 3: Renewable / Solar Energy (4 suggestions)
    # =========================================================================

    # 9. APPROVED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_RENEWABLE,
            suggestion=Suggestion(
                id="sugg-solar-001",
                content=SuggestionContent(
                    title="توسعه نیروگاه‌های فتوولتائیک خورشیدی روی سقف پست‌های توزیع جهت کاهش بار تلفات داخلی و پایداری شبکه",
                    problem=(
                        "فضای سقف و حیاط پست‌های توزیع بلااستفاده مانده و در ساعات ظهر تابستان تلفات ناشی از تهویه پست بسیار بالا است."
                    ),
                    solution=(
                        "نصب پنل‌های خورشیدی مونوکریستال ۵۵۰ وات به همراه اینورترهای متصل به شبکه هوشمند با امکان تزریق توان راکتیو جهت بهبود ولتاژ."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.APPROVED,
                    scrutiny=CommitteeScrutiny.APPROVED,
                    description="طرح در کارگروه بهره‌وری انرژی و انرژی‌های پاک تصویب و مقرر شد سقف ۲۰ پست نمونه تجهیز گردد.",
                    scrutiny_id=0,
                ),
                date=ShamsiDate("1402/02/18"),
                context_title="شرکت توزیع نیروی برق یزد",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
                    comment="دارای توجیه اقتصادی مشخص و انطباق با سیاست‌های کاهش کربن توانیر.",
                    scrutiny_id=3,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 10. PENDING, moderate description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_RENEWABLE,
            suggestion=Suggestion(
                id="sugg-solar-002",
                content=SuggestionContent(
                    title="سامانه پیش‌بینی توان خروجی مزارع خورشیدی با داده‌های ماهواره‌ای و رادار هواشناسی جهت مدیریت دیسپاچینگ",
                    problem=(
                        "نوسانات ناگهانی تابش بر اثر عبور ابرها پایداری فرکانس ریزشبکه‌ها را مختل و نیاز به ذخیره‌سازهای پرهزینه ایجاد می‌کند."
                    ),
                    solution=(
                        "ترکیب تصاویر ماهواره‌ای ابرهای پوششی با مدل‌های یادگیری عمیق ConvLSTM برای پیش‌بینی ۱۵ دقیقه‌ای تولید نیروگاه‌های فتوولتائیک."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.PENDING,
                    scrutiny=CommitteeScrutiny.PILOT_EXECUTION,
                    description="برای راه‌اندازی آزمایشی در مرکز دیسپاچینگ منطقه‌ای جنوب شرق در نظر گرفته شد.",
                    scrutiny_id=-7,
                ),
                date=ShamsiDate("1402/09/02"),
                context_title="شرکت برق منطقه‌ای کرمان",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 11. REJECTED, empty description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_RENEWABLE,
            suggestion=Suggestion(
                id="sugg-solar-003",
                content=SuggestionContent(
                    title="نصب آینه‌های مقعر متمرکزکننده نور بر روی دکل‌های فشار قوی خطوط انتقال جهت روشنایی شبانه",
                    problem=(
                        "روشنایی حریم خطوط انتقال در شب هزینه بالایی دارد و نیاز به کابل‌کشی‌های مستقل دارد."
                    ),
                    solution=(
                        "استفاده از آینه‌های بازتاب‌دهنده نور خورشید نصب شده روی بدنه دکل‌ها برای متمرکز کردن نور خورشید در روز و بازتاب آن در شب."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.REJECTED,
                    scrutiny=CommitteeScrutiny.NOT_FEASIBLE,
                    description=None,  # Empty evaluation
                    scrutiny_id=18,
                ),
                date=ShamsiDate("1401/08/14"),
                context_title="شرکت برق منطقه‌ای فارس",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REJECTED,
                    comment="از لحاظ اصول فیزیکی و ایمنی حریم خطوط برق فشار قوی کاملاً غیرممکن و خطرناک است.",
                    scrutiny_id=9,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 12. EXECUTED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_RENEWABLE,
            suggestion=Suggestion(
                id="sugg-solar-004",
                content=SuggestionContent(
                    title="الگوریتم ردیابی نقطه بیشینه توان (MPPT) سریع مبتنی بر شبکه عصبی برای اینورترهای خورشیدی در شرایط سایه‌اندازی",
                    problem=(
                        "الگوریتم‌های متداول P&O در مواجهه با سایه‌های موضعی به دام اکسترمم‌های محلی افتاده و ۲۰ درصد راندمان را هدر می‌دهند."
                    ),
                    solution=(
                        "پیاده‌سازی الگوریتم عصبی بهینه‌شده روی کنترل‌کننده‌های DSP اینورتر برای اسکن آنی منحنی I-V و یافتن نقطه توان بیشینه سراسری."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.EXECUTED,
                    scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                    description="به عنوان استاندارد نرم‌افزاری اینورترهای تولید داخل شرکت‌های همکار مورد استفاده قرار گرفت.",
                    scrutiny_id=6,
                ),
                date=ShamsiDate("1400/04/10"),
                context_title="شرکت توزیع نیروی برق البرز",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # =========================================================================
    # CLUSTER 4: Transmission & High-Voltage Protection (4 suggestions)
    # =========================================================================

    # 13. APPROVED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_TRANSMISSION,
            suggestion=Suggestion(
                id="sugg-trans-001",
                content=SuggestionContent(
                    title="هماهنگی تطبیقی رله‌های اضافه جریان و دیستانس شبکه انتقال در حضور منابع تولید پراکنده با منطق فازی",
                    problem=(
                        "اتصال منابع تولید پراکنده و نیروگاه‌های خورشیدی جریان اتصال کوتاه را دچار نوسان کرده و هماهنگی سنتی رله‌ها را با اختلال مواجه می‌کند."
                    ),
                    solution=(
                        "استقرار سیستم رله‌گذاری تطبیقی بر بستر استاندارد IEC 61850 با به‌روزرسانی برخط منحنی‌های تریپ متناسب با توپولوژی روز شبکه."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.APPROVED,
                    scrutiny=CommitteeScrutiny.APPROVED,
                    description="طرح در کمیته حفاظت و رله تصویب و جهت پیاده‌سازی در رینگ انتقال ۲۳۰ کیلوولت ابلاغ گردید.",
                    scrutiny_id=0,
                ),
                date=ShamsiDate("1402/03/22"),
                context_title="شرکت برق منطقه‌ای تهران",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
                    comment="مطالعات شبیه‌سازی در محیط DIgSILENT ضمیمه پرونده گردیده است.",
                    scrutiny_id=3,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 14. PENDING, moderate description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_TRANSMISSION,
            suggestion=Suggestion(
                id="sugg-trans-002",
                content=SuggestionContent(
                    title="استفاده از پهپادهای خودران هوشمند مجهز به دوربین ترموویژن و لیدار برای بازرسی دکل‌ها و مقره‌های خطوط انتقال",
                    problem=(
                        "بازرسی چشمی و صعود سیمبانان از دکل‌های صعب‌العبور زمان‌بر، پرهزینه و همراه با خطرات جانی سقوط و برق‌گرفتگی است."
                    ),
                    solution=(
                        "برنامه‌ریزی مسیر پرواز خودکار پهپادها با استفاده از داده‌های لیدار، تصویربرداری فروسرخ از مقره‌ها و شناسایی خودکار اتصالات داغ."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.PENDING,
                    scrutiny=CommitteeScrutiny.PILOT_EXECUTION,
                    description="تصویب پایلوت برای خطوط ۴۰۰ کیلوولت کوهستانی در معاونت بهره‌برداری انتقال.",
                    scrutiny_id=-7,
                ),
                date=ShamsiDate("1402/10/05"),
                context_title="شرکت برق منطقه‌ای مازندران و گلستان",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 15. NOT_ACCEPTED, empty description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_TRANSMISSION,
            suggestion=Suggestion(
                id="sugg-trans-003",
                content=SuggestionContent(
                    title="رنگ‌آمیزی دکل‌های خطوط ۴۰۰ کیلوولت با رنگ‌های فسفری شب‌تاب جهت حذف زنجیره‌های مقره",
                    problem=(
                        "زنجیره‌های مقره سرامیکی و شیشه‌ای خطوط انتقال دچار آلودگی و شکست الکتریکی و جرقه سطحی می‌شوند."
                    ),
                    solution=(
                        "حذف مقره‌ها و رنگ‌آمیزی مستقیم بازوهای فلزی دکل‌ها با پوشش‌های نانو فسفری شب‌تاب برای عایق‌سازی هادی‌ها."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.NOT_ACCEPTED,
                    scrutiny=CommitteeScrutiny.BEYOND_AUTHORITY_CONTRARY_TO_POLICIES,
                    description=None,  # Empty evaluation
                    scrutiny_id=10,
                ),
                date=ShamsiDate("1401/05/19"),
                context_title="شرکت برق منطقه‌ای خوزستان",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.NOT_A_SUGGESTION,
                    comment="مغایر با تمامی اصول مسلم مهندسی فشار قوی و خطرات جدی انهدام شبکه.",
                    scrutiny_id=8,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 16. EXECUTED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_TRANSMISSION,
            suggestion=Suggestion(
                id="sugg-trans-004",
                content=SuggestionContent(
                    title="الگوریتم تشخیص امپدانس بالای خطای تک‌فاز به زمین در شبکه‌های انتقال جبران‌شده با کویل پترسن",
                    problem=(
                        "خطاهای تک‌فاز با مقاومت بالا (مانند برخورد شاخه درخت) توسط رله‌های سنتی زمین شناسایی نشده و خطر آتش‌سوزی حریم دارد."
                    ),
                    solution=(
                        "تحلیل مولفه‌های هارمونیکی مرتبه پنج و تغییرات زاویه فاز ولتاژ توالی صفر برای کشف دقیق خطای امپدانس بالا."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.EXECUTED,
                    scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                    description="الگوریتم در رله‌های بومی پست انتقال شهید فیروزی بارگذاری و عملکرد موفقیت‌آمیز داشته است.",
                    scrutiny_id=6,
                ),
                date=ShamsiDate("1400/11/12"),
                context_title="شرکت برق منطقه‌ای آذربایجان",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # =========================================================================
    # CLUSTER 5: IT / Cybersecurity (4 suggestions)
    # =========================================================================

    # 17. APPROVED, rich commentary
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_CYBERSECURITY,
            suggestion=Suggestion(
                id="sugg-cyber-001",
                content=SuggestionContent(
                    title="طراحی معماری اعتماد صفر (Zero Trust) و امن‌سازی لایه‌های ارتباطی پروتکل‌های اتوماسیون پست‌های SCADA",
                    problem=(
                        "نفوذ به شبکه‌های کنترل صنعتی و دستکاری پکت‌های پروتکل‌های IEC 60870-5-104 و DNP3 تهدید جدی خاموشی سراسری ایجاد می‌کند."
                    ),
                    solution=(
                        "استقرار دیواره‌های آتش صنعتی بومی، احراز هویت دوعاملی برای دسترسی‌های ریموت، و تونل‌های رمزنگاری شده IPSec سخت‌افزاری."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.APPROVED,
                    scrutiny=CommitteeScrutiny.APPROVED,
                    description="طرح در کمیته پدافند غیرعامل و امنیت فناوری اطلاعات تصویب و مشمول اولویت بودجه‌ای قرار گرفت.",
                    scrutiny_id=0,
                ),
                date=ShamsiDate("1402/06/08"),
                context_title="شرکت توانیر - ستاد مرکزی",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
                    comment="پیشنهاد مستقیماً در راستای سند افتا و ابلاغیه‌های امنیت زیرساخت‌های حیاتی است.",
                    scrutiny_id=3,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 18. PENDING, moderate description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_CYBERSECURITY,
            suggestion=Suggestion(
                id="sugg-cyber-002",
                content=SuggestionContent(
                    title="سامانه فریب سایبری (Honeypot) اختصاصی سیستم‌های اسکادا و تجهیزات شبکه هوشمند برق",
                    problem=(
                        "شناسایی دیرهنگام حملات هدفمند APT به مراکز دیسپاچینگ می‌تواند منجر به سرقت اطلاعات محرمانه توپولوژی شبکه گردد."
                    ),
                    solution=(
                        "شبیه‌سازی مجازی کنترل‌کننده‌های RTU و سامانه‌های تلمتری در یک محیط ایزوله جهت فریب مهاجمان و تحلیل بردارهای حمله."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.PENDING,
                    scrutiny=CommitteeScrutiny.SEND_FOR_EXPERT_OPINION,
                    description="جهت ارزیابی تست نفوذپذیری به تیم مرکز ماهر و امنیت اطلاعات ارجاع گردید.",
                    scrutiny_id=-8,
                ),
                date=ShamsiDate("1402/11/17"),
                context_title="شرکت مدیریت شبکه برق ایران",
                secretariat_evaluation=None,
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 19. REJECTED, empty description
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_CYBERSECURITY,
            suggestion=Suggestion(
                id="sugg-cyber-003",
                content=SuggestionContent(
                    title="اتصال سرورهای دیسپاچینگ ملی به شبکه اینترنت عمومی جهت تسهیل دورکاری اپراتورها در روزهای تعطیل",
                    problem=(
                        "حضور فیزیکی اپراتورهای دیسپاچینگ در شیفت‌های شب و روزهای برفی در مرکز دیسپاچینگ دشوار و هزینه‌بر است."
                    ),
                    solution=(
                        "قرار دادن اینترفیس مدیریت وب سرورهای اسکادا بر روی آی‌پی عمومی اینترنت با یک نام کاربری و کلمه عبور مشترک سازمانی."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.REJECTED,
                    scrutiny=CommitteeScrutiny.BEYOND_AUTHORITY_CONTRARY_TO_POLICIES,
                    description=None,  # Empty evaluation
                    scrutiny_id=10,
                ),
                date=ShamsiDate("1401/10/12"),
                context_title="شرکت توانیر - ستاد مرکزی",
                secretariat_evaluation=SecretariatEvaluation(
                    scrutiny=SecretariatScrutiny.REJECTED,
                    comment="نقض فاحش اصول پدافند غیرعامل و دستورالعمل‌های حفاظتی زیرساخت‌های حیاتی کشور.",
                    scrutiny_id=9,
                ),
                is_deleted=False,
                version=1,
            ),
        )
    )

    # 20. SOFT-DELETED suggestion edge case, EXECUTED
    items.append(
        ClusteredSuggestion(
            cluster=CLUSTER_CYBERSECURITY,
            suggestion=Suggestion(
                id="sugg-cyber-004",
                content=SuggestionContent(
                    title="نرم‌افزار جامع مدیریت آسیب‌پذیری‌ها و تطابق پیکربندی سوئیچ‌ها و روترهای شبکه اداری و صنعتی شرکت",
                    problem=(
                        "پیکربندی‌های دستی و تغییرات بدون ثبت در روترها و سوئیچ‌های شبکه منجر به ایجاد حفره‌های امنیتی ناخواسته می‌شود."
                    ),
                    solution=(
                        "توسعه سامانه بررسی انطباق خودکار با چک‌لیست‌های CIS Benchmarks و اعمال سیاست‌های امنیتی یکپارچه از طریق کدهای Ansible."
                    ),
                ),
                evaluation=CommitteeEvaluation(
                    status=SuggestionStatus.EXECUTED,
                    scrutiny=CommitteeScrutiny.ACCEPTED_AS_EXECUTED_SUGGESTION,
                    description="طرح با موفقیت اجرایی شد اما به دلیل تغییر سامانه‌های مدیریتی منسوخ و بایگانی شده است.",
                    scrutiny_id=6,
                ),
                date=ShamsiDate("1399/12/20"),
                context_title="شرکت برق منطقه‌ای اصفهان",
                secretariat_evaluation=None,
                is_deleted=True,  # Soft-deleted edge case!
                version=3,
            ),
        )
    )

    return items


import uuid


def deterministic_chunk_id(tag: str) -> str:
    """Generates a RFC 4122 compliant UUIDv5 string from a deterministic seed tag."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tavanir-corpus:{tag}"))


REG_CHUNK_DIST_001 = deterministic_chunk_id("reg-dist-001")
REG_CHUNK_DIST_002 = deterministic_chunk_id("reg-dist-002")
REG_CHUNK_METER_001 = deterministic_chunk_id("reg-meter-001")
REG_CHUNK_METER_002 = deterministic_chunk_id("reg-meter-002")
REG_CHUNK_SOLAR_001 = deterministic_chunk_id("reg-solar-001")
REG_CHUNK_SOLAR_002 = deterministic_chunk_id("reg-solar-002")
REG_CHUNK_TRANS_001 = deterministic_chunk_id("reg-trans-001")
REG_CHUNK_TRANS_002 = deterministic_chunk_id("reg-trans-002")
REG_CHUNK_CYBER_001 = deterministic_chunk_id("reg-cyber-001")
REG_CHUNK_CYBER_002 = deterministic_chunk_id("reg-cyber-002")


# ---------------------------------------------------------------------------
# Regulatory Corpus (10 documents across 5 clusters)
# ---------------------------------------------------------------------------
def _build_regulatory_chunks() -> list[ClusteredRegulatoryChunk]:
    items: list[ClusteredRegulatoryChunk] = []

    # CLUSTER 1: Distribution / Grid Transformers (2 docs)
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_DISTRIBUTION,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_DIST_001,
                parent_id="reg-doc-dist-001",
                content=(
                    "دستورالعمل جامع سرویس، نگهداری و عیب‌یابی ترانسفورماتورهای توزیع هوایی و زمینی: "
                    "ماده ۳ - تمامی شرکت‌های توزیع نیروی برق موظفند سالانه نسبت به نمونه‌برداری از روغن عایق ترانسفورماتورهای "
                    "با ظرفیت ۴۰۰ کیلوولت‌آمپر و بالاتر جهت تست ولتاژ شکست دی‌الکتریک و اندازه‌گیری میزان گازهای محلول (DGA) "
                    "اقدام نمایند. در صورت کاهش ولتاژ شکست به کمتر از ۳۰ کیلوولت در فاصله ۲.۵ میلی‌متری، ترانسفورماتور باید بلافاصله "
                    "تحت عملیات تصفیه فیزیکی و گاززدایی قرار گیرد."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="دستورالعمل سرویس و نگهداری ترانسفورماتورهای شبکه توزیع",
                    document_type=RegulatoryDocumentType.PROCEDURE,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_DISTRIBUTION,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_DIST_002,
                parent_id="reg-doc-dist-002",
                content=(
                    "شیوه‌نامه نظارت بر بار حرارتی و پیشگیری از اضافه بار ترانسفورماتورهای شبکه توزیع: "
                    "بند ۲-۴ - توصیه می‌شود در پست‌های توزیع عمومی پربار، از سامانه‌های پایش برخط دما و تراز روغن با استفاده از "
                    "حسگرهای مدرن بهره‌گیری شود. دمای روغن بالایی ترانسفورماتور در شرایط نامی نباید از ۶۵ درجه سانتی‌گراد بیش از دمای محیط "
                    "افزایش یابد و دمای نقطه داغ سیم‌پیچ‌ها باید همواره زیر ۹۸ درجه سانتی‌گراد مهار گردد."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="شیوه‌نامه نظارت بر بار حرارتی ترانسفورماتورها",
                    document_type=RegulatoryDocumentType.GUIDELINE,
                    is_binding=False,
                    authority_level=AuthorityLevel.GUIDANCE,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )

    # CLUSTER 2: Smart Metering / Billing (2 docs)
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_METERING,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_METER_001,
                parent_id="reg-doc-meter-001",
                content=(
                    "قانون توسعه و پیاده‌سازی طرح فراسامانه هوشمند اندازه‌گیری و مدیریت انرژی (فهام): "
                    "ماده ۶ - نصب کنتورهای هوشمند با قابلیت اندازه‌گیری چندزمانه، ثبت پروفایل بار، تبادل داده دوطرفه و امکان قطع و وصل "
                    "از راه دور برای کلیه مشترکین دیماندی صنعتی، کشاورزی و تجاری بزرگ الزامی است. داده‌های کنتورها باید منطبق با پروتکل "
                    "بین‌المللی DLMS/COSEM و تحت لایه امنیتی استاندارد به سامانه ملی MDM ارسال شود."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="قانون توسعه فراسامانه هوشمند اندازه‌گیری انرژی (طرح فهام)",
                    document_type=RegulatoryDocumentType.STATUTE,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_METERING,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_METER_002,
                parent_id="reg-doc-meter-002",
                content=(
                    "آیین‌نامه نحوه محاسبه تعرفه‌های فصلی و پویای برق و نظارت بر لوازم اندازه‌گیری: "
                    "ماده ۸ - شرکت‌های توزیع برق مکلفند در صورت کشف هرگونه دستکاری، فک پلمب یا ایجاد خطای عمدی در لوازم اندازه‌گیری "
                    "که منجر به عدم ثبت تمام یا بخشی از انرژی مصرفی گردد، بر اساس فرمول محاسباتی مابه‌التفاوت مصرف واقعی به انضمام "
                    "جرایم دیرکرد و خسارت به شبکه را وصول نمایند."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="آیین‌نامه نحوه محاسبه تعرفه‌ها و نظارت بر لوازم اندازه‌گیری",
                    document_type=RegulatoryDocumentType.REGULATION,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )

    # CLUSTER 3: Renewable / Solar Energy (2 docs)
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_RENEWABLE,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_SOLAR_001,
                parent_id="reg-doc-solar-001",
                content=(
                    "قانون حمایت از توسعه صنعت برق و خرید تضمینی برق از نیروگاه‌های تجدیدپذیر: "
                    "ماده ۲ - وزارت نیرو موظف است برق تولیدی از منابع تجدیدپذیر بادی و خورشیدی را به صورت قراردادهای بلندمدت ۲۰ ساله "
                    "با نرخ‌های تضمینی مصوب هیئت وزیران خریداری نماید. نیروگاه‌های متصل به شبکه توزیع مشمول مشوق‌های عدم اشغال ظرفیت "
                    "انتقال و کاهش تلفات شبکه می‌گردند."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="قانون خرید تضمینی برق تجدیدپذیر و پاک",
                    document_type=RegulatoryDocumentType.STATUTE,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_RENEWABLE,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_SOLAR_002,
                parent_id="reg-doc-solar-002",
                content=(
                    "بخشنامه ضوابط فنی و استانداردهای اتصال نیروگاه‌های خورشیدی فتوولتائیک به شبکه توزیع: "
                    "ماده ۴ - اینورترهای خورشیدی متصل به شبکه توزیع باید مجهز به حفاظت ضدجزیره‌ای (Anti-Islanding) فعال بوده و در صورت "
                    "قطع برق شبکه ظرف مدت حداکثر ۲ ثانیه تزریق توان را متوقف سازند. هارمونیک تزریقی کل جریان (THD) نباید از ۵ درصد تجاوز نماید."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="ضوابط فنی اتصال نیروگاه‌های فتوولتائیک به شبکه توزیع",
                    document_type=RegulatoryDocumentType.DIRECTIVE,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )

    # CLUSTER 4: Transmission & High-Voltage Protection (2 docs)
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_TRANSMISSION,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_TRANS_001,
                parent_id="reg-doc-trans-001",
                content=(
                    "دستورالعمل جامع هماهنگی رله‌های حفاظتی و پایداری شبکه انتقال و فوق‌توزیع (کد شبکه): "
                    "ماده ۱۲ - کلیه خطوط انتقال ۲۳۰ و ۴۰۰ کیلوولت باید دارای دو سیستم حفاظت اصلی مستقل (Main 1 و Main 2) از نوع دیستانس "
                    "یا دیفرانسیل خط مبتنی بر تبادل سیگنال فیبر نوری باشند. زمان عملکرد حفاظت اصلی در خطاهای درون زون اول نباید از ۳۰ میلی‌ثانیه بیشتر باشد."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="دستورالعمل جامع هماهنگی رله‌های حفاظتی شبکه انتقال",
                    document_type=RegulatoryDocumentType.PROCEDURE,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_TRANSMISSION,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_TRANS_002,
                parent_id="reg-doc-trans-002",
                content=(
                    "شیوه‌نامه بازرسی دوره‌ای خطوط انتقال نیرو و نگهداری حریم خطوط فشار قوی: "
                    "بند ۷ - پایش دمایی مقره‌ها و اتصالات خطوط انتقال از طریق دوربین‌های ترموویژن و بالگرد یا پهپاد حداقل دو بار در سال "
                    "به ویژه قبل از شروع پیک تابستان الزامی است. هرگونه کانون حرارتی با اختلاف دمای بیش از ۱۵ درجه نسبت به قطعات مجاور "
                    "به عنوان عیب درجه یک و نیازمند تعمیر فوری تلقی می‌گردد."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="شیوه‌نامه بازرسی دوره‌ای خطوط انتقال نیرو",
                    document_type=RegulatoryDocumentType.GUIDELINE,
                    is_binding=False,
                    authority_level=AuthorityLevel.GUIDANCE,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )

    # CLUSTER 5: IT / Cybersecurity (2 docs)
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_CYBERSECURITY,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_CYBER_001,
                parent_id="reg-doc-cyber-001",
                content=(
                    "بخشنامه الزامات امنیت سایبری سامانه‌های کنترل صنعتی، اسکادا و دیسپاچینگ صنعت برق: "
                    "ماده ۵ - هرگونه اتصال مستقیم فیزیکی یا منطقی میان شبکه دیسپاچینگ (OT) و شبکه فناوری اطلاعات سازمانی (IT) یا شبکه اینترنت "
                    "اکیداً ممنوع است. تبادل داده میان این دو ناحیه صرفاً باید از طریق دیواره‌های آتش صنعتی یکطرفه (Data Diode) با مجوز مرکز امنیت صورت پذیرد."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="الزامات امنیت سایبری سامانه‌های اسکادا و دیسپاچینگ",
                    document_type=RegulatoryDocumentType.DIRECTIVE,
                    is_binding=True,
                    authority_level=AuthorityLevel.BINDING,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )
    items.append(
        ClusteredRegulatoryChunk(
            cluster=CLUSTER_CYBERSECURITY,
            chunk=Chunk[RegulatoryChunkMetadata](
                chunk_id=REG_CHUNK_CYBER_002,
                parent_id="reg-doc-cyber-002",
                content=(
                    "شیوه‌نامه مدیریت دسترسی و احراز هویت در شبکه‌های هوشمند و زیرساخت‌های حیاتی برق: "
                    "بند ۳ - تمامی دسترسی‌های راه دور مدیریتی به سرورها و پایگاه‌های داده عملیاتی صنعت برق باید با اعمال احراز هویت "
                    "چندعاملی (MFA)، ثبت کامل لاگ‌های وقایع و رمزنگاری داده‌های در حال انتقال با کلیدهای امنیتی معتبر صورت پذیرد."
                ),
                metadata=RegulatoryChunkMetadata(
                    document_title="شیوه‌نامه احراز هویت و امنیت شبکه در صنعت برق",
                    document_type=RegulatoryDocumentType.GUIDELINE,
                    is_binding=False,
                    authority_level=AuthorityLevel.GUIDANCE,
                ),
                chunk_status=ChunkStatus.ACTIVE,
            ),
        )
    )

    return items


# Cache lists and mappings
_SUGGESTIONS_CACHE: list[ClusteredSuggestion] = _build_suggestions()
_REGULATORY_CACHE: list[ClusteredRegulatoryChunk] = _build_regulatory_chunks()

SUGGESTION_CLUSTER_MAP: dict[str, str] = {
    item.suggestion.id: item.cluster for item in _SUGGESTIONS_CACHE
}

REGULATORY_CLUSTER_MAP: dict[str, str] = {
    item.chunk.chunk_id: item.cluster for item in _REGULATORY_CACHE
}


def get_seed_suggestions() -> list[Suggestion]:
    """Returns the 20 golden benchmark employee suggestions."""
    return [item.suggestion for item in _SUGGESTIONS_CACHE]


def get_seed_regulatory_chunks() -> list[RegulatoryChunk]:
    """Returns the 10 golden benchmark regulatory chunks."""
    return [item.chunk for item in _REGULATORY_CACHE]


def get_suggestion_cluster(suggestion_id: str) -> str:
    """Returns the cluster identifier for a given suggestion id."""
    return SUGGESTION_CLUSTER_MAP[suggestion_id]


def get_regulatory_cluster(chunk_id: str) -> str:
    """Returns the cluster identifier for a given regulatory chunk id."""
    return REGULATORY_CLUSTER_MAP[chunk_id]
