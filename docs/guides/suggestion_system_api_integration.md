<div dir="rtl" style="text-align: right; font-family: Tahoma, 'Vazirmatn', sans-serif; line-height: 1.8;">

# راهنمای جامع اتصال و یکپارچه‌سازی وب‌سرویس‌های دستیار هوشمند توانیر (نسخه ۲)
## ویژه توسعه‌دهندگان سامانه نظام پیشنهادات (API Integration Guide)

> **Generation status:** Analyze returns parsed model analysis with usable evidence; expansion returns five parsed fields. See the [Generation guide](../documentation/llm_generation_api.md) for the current expansion marker mismatch and verification limits.
> **مخاطب:** تیم فنی و توسعه‌دهندگان سامانه نظام پیشنهادات  
> **پروتکل ارتباطی:** RESTful HTTP API / JSON:API  
> **نسخه وب‌سرویس:** `2.0.0`  
> **روش احراز هویت:** کلید اختصاصی سرویس (`X-API-Key`)

---

## فهرست مطالب
1. [مقدمه و دامنه کاربرد](#۱-مقدمه-و-دامنه-کاربرد)
2. [اصول ارتباطی، فرمت تبادل داده و قواعد نام‌گذاری](#۲-اصول-ارتباطی-فرمت-تبادل-داده-و-قواعد-نام‌گذاری)
3. [امنیت و احراز هویت سرویس (Authentication & Tracing)](#۳-امنیت-و-احراز-هویت-سرویس-authentication--tracing)
4. [مرجع کامل اندپوینت‌ها (API Endpoints Reference)](#۴-مرجع-کامل-اندپوینت‌ها-api-endpoints-reference)
   - [۴.۱. تحلیل پیشنهادات جدید (`POST /suggestions/analyze`)](#۴۱-تحلیل-پیشنهادات-جدید-post-suggestionsanalyze)
   - [۴.۲. نمایه‌سازی پیشنهاد در پایگاه دانش (`POST /suggestions/ingest`)](#۴۲-نمایه‌سازی-پیشنهاد-در-پایگاه-دانش-post-suggestionsingest)
   - [۴.۳. بازنویسی و به‌روزرسانی کامل پیشنهاد (`PUT /suggestions/{suggestionId}`)](#۴۳-بازنویسی-و-به‌روزرسانی-کامل-پیشنهاد-put-suggestionssuggestionid)
   - [۴.۴. ویرایش جزئی مشخصات پیشنهاد (`PATCH /suggestions/{suggestionId}`)](#۴۴-ویرایش-جزئی-مشخصات-پیشنهاد-patch-suggestionssuggestionid)
   - [۴.۵. عملیات Soft Delete پیشنهاد و پاک‌سازی بردارها (`DELETE /suggestions/{suggestionId}`)](#۴۵-عملیات-soft-delete-پیشنهاد-و-پاک‌سازی-بردارها-delete-suggestionssuggestionid)
   - [۴.۶. حذف دسته‌ای پیشنهادات (`POST /suggestions/bulk-delete`)](#۴۶-حذف-دسته‌ای-پیشنهادات-post-suggestionsbulk-delete)
   - [۴.۷. پایش سلامت سرویس (`GET /health`)](#۴۷-پایش-سلامت-سرویس-get-health)
5. [راهنمای مصرف و پردازش پاسخ تحلیل در سامانه مقصد](#۵-راهنمای-مصرف-و-پردازش-پاسخ-تحلیل-در-سامانه-مقصد)
6. [مدیریت خطا و دیکشنری کدهای اختصاصی (Error Handling)](#۶-مدیریت-خطا-و-دیکشنری-کدهای-اختصاصی-error-handling)
7. [چک‌لیست پیاده‌سازی و اعتبارسنجی اتصال](#۷-چک‌لیست-پیاده‌سازی-و-اعتبارسنجی-اتصال)

---

## ۱. مقدمه و دامنه کاربرد

سرویس **Tavanir AI Assistant V2** یک زیرسیستم پردازش شناختی و بازیابی اطلاعات سازمانی (RAG) است که برای اتصال به سامانه مرکزی نظام پیشنهادات شرکت توانیر طراحی شده است. این سرویس امکانات زیر را فراهم می‌کند:

- **کشف سوابق و پیشنهادات مشابه:** جستجوی معنایی و هیبریدی در کل سوابق پیشنهادات ادوار گذشته صنعت برق بر اساس محتوای مسئله و راهکار.
- **تطبیق با اسناد بالادستی و مصوبات:** ارزیابی پیشنهاد ارائه‌شده در برابر قوانین، آیین‌نامه‌ها و بخشنامه‌های معتبر توانیر *(این بخش در حال حاضر در دست توسعه است و تحلیل جاری صرفاً بر اساس پیشنهادات مشابه صورت می‌گیرد)*.
- **Generated decision support:** Analyze maps validated model output to `analysis`, with cited IDs and uncertainty. Expansion turns a short idea into five parsed fields. These results require human review.
- **مدیریت پایگاه دانش برداری:** همگام‌سازی لحظه‌ای بردارها و سوابق پیشنهادات هم‌زمان با چرخه تغییر وضعیت در سامانه نظام پیشنهادات.

---

## ۲. اصول ارتباطی، فرمت تبادل داده و قواعد نام‌گذاری

رعایت استانداردهای زیر جهت ایجاد ارتباط پایدار و بدون خطای اعتبارسنجی الزامی است:

### ۲.۱. استاندارد کپسوله‌سازی پاسخ‌ها (JSON:API Envelope)
تمامی پاسخ‌های این سرویس در یک قالب ساختاریافته ارسال می‌شوند:
- **پاسخ‌های موفق (کدهای وضعیت 2xx):**
  - فیلد `status`: کد وضعیت HTTP مربوطه (مانند 200 یا 202).
  - فیلد `data`: شامل بدنه اصلی داده (یک شیء تک یا آرایه‌ای از اشیاء).
- **پاسخ‌های ناموفق (کدهای وضعیت 4xx و 5xx):**
  - فیلد `errors`: آرایه‌ای از اشیاء خطا شامل `status`، کد داخلی `code`، و شیء `source.pointer` جهت اشاره دقیق به فیلد مشکل‌دار در بدنه درخواست (مطابق استاندارد RFC 6901).
- **پاسخ عملیات دسته‌ای با موفقیت جزئی (207 Multi-Status):**
  - هم‌زمان شامل فیلد `data` (اقلام با موفقیت پردازش‌شده) و فیلد `errors` (اقلام شکست‌خورده) خواهد بود.

### ۲.۲. قاعده نام‌گذاری فیلدها (camelCase)
تمامی کلیدها و فیلدهای ارسالی و دریافتی در بدنه JSON، پارامترهای مسیر URL (Path Parameters) و پارامترهای پرس‌وجو (Query String) باید مطابق استاندارد **`camelCase`** ارسال شوند (مانند `currentProblem`، `contextTitle`، `suggestionId`).

### ۲.۳. جدول مقادیر معتبر وضعیت پیشنهاد (SuggestionStatus)
سرویس برای شناسایی وضعیت پیشنهادات صرفاً شناسه‌های متنی استاندارد زیر را می‌پذیرد. از ارسال نام‌های فارسی آزاد یا شناسه‌های عددی در فیلد `status` خودداری فرمایید:

| شناسه قراردادی (Wire Code) | عنوان فارسی معادل | شناسه عددی پیشین (Legacy ID) | وضعیت گردش‌کار در سامانه |
| :--- | :--- | :---: | :--- |
| `NOT_ACCEPTED` | عدم پذیرش | ۱ | رد شده در مرحله غربالگری اولیه دبیرخانه |
| `REJECTED` | رد | ۲ | رد شده پس از طرح و ارزیابی در کمیته |
| `APPROVED` | مصوب | ۳ | تصویب شده در کمیته و در انتظار تخصیص مجری |
| `PENDING` | در حال اجرا | ۴ | در مرحله پیاده‌سازی و اجرای پروژه |
| `EXECUTED` | اجرا شده | ۵ | اجرای کامل پیشنهاد در توانیر با موفقیت پایان یافته |

---

## ۳. امنیت و احراز هویت سرویس (Authentication & Tracing)

ارتباط میان سامانه نظام پیشنهادات و سرویس دستیار هوشمند به صورت سرویس‌به‌سرویس (Machine-to-Machine) و بدون حالت (Stateless) است:

### ۳.۱. هدر احراز هویت (`X-API-Key`)
کلیه درخواست‌ها (به جز اندپوینت عمومی `/health`) باید شامل هدر زیر باشند:

<div dir="ltr" style="text-align: left;">

```http
X-API-Key: YOUR_ASSIGNED_SECRET_API_KEY
```

</div>

در صورت عدم ارسال هدر یا نامعتبر بودن مقدار آن، خطای `401 Unauthorized` با کد داخلی `API_KEY_MISSING` یا `API_KEY_INVALID` برگردانده خواهد شد.

### ۳.۲. هدر ردیابی توزیع‌شده (`X-Request-Id`)
جهت همگام‌سازی لاگ‌ها، عیب‌یابی خطاهای شبکه و پیگیری تراکنش‌ها، توصیه می‌شود برای هر درخواست یک شناسه یکتای UUID v4 در هدر زیر ارسال شود:

<div dir="ltr" style="text-align: left;">

```http
X-Request-Id: c3b91a56-8e12-4f81-9b1b-6cb76135cf91
```

</div>

---

## ۴. مرجع کامل اندپوینت‌ها (API Endpoints Reference)

آدرس پایه دسترسی به سرویس:
<div dir="ltr" style="text-align: left;">

```
https://<HOST>:<PORT>/api/v1
```

</div>

---

### ۴.۱. تحلیل پیشنهادات جدید (`POST /suggestions/analyze`)

After usable evidence has been prepared by the existing upstream flow, this endpoint invokes the injected generator, fits sections through ContextBuilder, calls the shared LLM, and validates its answer/citations/uncertainty. The existing no-evidence branch returns diagnostics without a model call.

> **توجه:** بخش تطبیق با اسناد بالادستی و قوانین در حال حاضر در دست توسعه است و تحلیل فعلی صرفاً بر اساس پیشنهادات مشابه موجود در سوابق انجام می‌پذیرد.

- **مسیر:** `/api/v1/suggestions/analyze`
- **متد:** `POST`
- **هدرهای الزامی:** `Content-Type: application/json` ، `X-API-Key: <SECRET>`

#### پارامترهای بدنه درخواست (Request Body):
| نام فیلد | نوع داده | الزامی؟ | شرح فیلد |
| :--- | :---: | :---: | :--- |
| `title` | string | بله | عنوان پیشنهاد ارائه‌شده |
| `currentProblem` | string | بله | شرح وضع موجود و مسئله‌ای که پیشنهاد برای حل آن مطرح شده |
| `solution` | string | بله | راهکار و پیشنهاد ارائه‌شده توسط پیشنهاددهنده |
| `contextTitle` | string | خیر | حوزه تخصصی یا رده موضوعی (مثال: "انتقال و دیسپاچینگ"، "امور مالی") |

#### نمونه درخواست (cURL):
<div dir="ltr" style="text-align: left;">

```bash
curl -X POST "https://ai-assistant.tavanir.org.ir/api/v1/suggestions/analyze" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secure-secret-key-123" \
  -H "X-Request-Id: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{
    "title": "بهینه‌سازی سیستم خنک‌کاری ترانسفورماتورهای فوق توزیع",
    "currentProblem": "افزایش دمای ترانسفورماتورها در ساعات اوج بار فصل تابستان موجب کاهش طول عمر عایقی و آسیب به بوبین‌ها می‌گردد.",
    "solution": "نصب فن‌های پربازده با حسگر دمای روغن و پیاده‌سازی سیستم مه‌پاش خودکار جهت تعدیل دما در ساعات پیک.",
    "contextTitle": "بهره‌برداری و انتقال"
  }'
```

</div>

#### مشخصات بدنه پاسخ (Response Body - 200 OK):
| فیلد | نوع داده | شرح فیلد |
| :--- | :---: | :--- |
| `analysis` | string | Parsed model answer on the normal path; diagnostic text when no usable evidence exists. |
| `similarExecutedIds` | string[] | آرایه شناسه‌های پیشنهادات مشابهی که در سازمان قبلاً اجرا شده‌اند |
| `similarApprovedIds` | string[] | آرایه شناسه‌های پیشنهادات مشابهی که مصوب شده و در نوبت اجرا هستند |
| `similarPendingIds` | string[] | آرایه شناسه‌های پیشنهادات مشابهی که هم‌اکنون در حال پیاده‌سازی هستند |
| `similarRejectedIds` | string[] | آرایه شناسه‌های پیشنهادات مشابهی که قبلاً در کمیته رد شده‌اند |
| `similarNotAcceptedIds` | string[] | آرایه شناسه‌های پیشنهادات مشابهی که در بررسی اولیه عدم پذیرش خورده‌اند |
| `appliedStatuteIds` | string[] | آرایه شناسه‌های قوانین مورد ارجاع (در فاز فعلی رزرو و مربوط به توسعه آتی است) |
| `citedSuggestionIds` | string[] | Unique original IDs actually cited by the model; separate from the candidate lists. |
| `uncertainty` | string or null | Parsed model uncertainty or the explicit no-evidence explanation. |
| `isFallbackMode` | boolean | Existing upstream fallback flag; not a model fallback indicator. |
| `groundingRatio` | number | Citation coverage of active candidates, rounded to two decimals; not calibrated confidence. |

#### نمونه پاسخ:
<div dir="ltr" style="text-align: left;">

```json
{
  "status": 200,
  "data": {
    "analysis": "Illustrative generated analysis: assess sensor reliability and installation costs before deployment.",
    "similarExecutedIds": ["sug-1042", "sug-879"],
    "similarApprovedIds": [],
    "similarPendingIds": ["sug-2210"],
    "similarRejectedIds": ["sug-451"],
    "similarNotAcceptedIds": [],
    "appliedStatuteIds": [],
    "citedSuggestionIds": ["sug-1042"],
    "uncertainty": "Installation costs have not been established.",
    "isFallbackMode": false,
    "groundingRatio": 0.25
  }
}
```

</div>

---

### ۴.۲. نمایه‌سازی پیشنهاد در پایگاه دانش (`POST /suggestions/ingest`)

هنگامی که یک پیشنهاد جدید ثبت شده یا به وضعیت نهایی در سامانه نظام پیشنهادات می‌رسد، از این متد جهت تجزیه متنی (Chunking)، تولید بردارها و ذخیره در پایگاه برداری (Qdrant) و دیتابیس رابطه‌ای استفاده می‌شود.

- **مسیر:** `/api/v1/suggestions/ingest`
- **متد:** `POST`

#### پارامترهای بدنه درخواست:
| نام فیلد | نوع داده | الزامی؟ | شرح |
| :--- | :---: | :---: | :--- |
| `suggestionId` | string | بله | شناسه یکتای پیشنهاد در سامانه نظام پیشنهادات |
| `title` | string | بله | عنوان پیشنهاد |
| `problem` | string | بله | شرح مسئله یا وضع موجود |
| `solution` | string | بله | شرح راهکار ارائه‌شده |
| `status` | string | بله | وضعیت پیشنهاد (یکی از مقادیر جدول بخش ۲.۳) |
| `shamsiDate` | string | خیر | تاریخ شمسی ثبت یا تصویب با فرمت `YYYY/MM/DD` |
| `contextTitle` | string | خیر | عنوان حوزه موضوعی پیشنهاد |
| `committeeScrutiny` | string | خیر | نظر یا مصوبه کارشناسی کمیته ارزیابی |
| `secretariatScrutiny` | string | خیر | نظر کارشناسی دبیرخانه |
| `description` | string | خیر | توضیحات تکمیلی یا پیوست‌ها |

#### نمونه درخواست (cURL):
<div dir="ltr" style="text-align: left;">

```bash
curl -X POST "https://ai-assistant.tavanir.org.ir/api/v1/suggestions/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secure-secret-key-123" \
  -d '{
    "suggestionId": "sug-4892",
    "title": "استفاده از پهپاد جهت بازرسی خطوط انتقال نیرو",
    "problem": "پایش چشمی دکل‌ها و سیم‌های خطوط انتقال در مناطق کوهستانی بسیار پرهزینه و پرخطر است.",
    "solution": "به‌کارگیری کوادکوپترهای مجهز به دوربین ترموویژن برای پایش اتصالات و مقره‌ها.",
    "status": "APPROVED",
    "shamsiDate": "1403/05/18",
    "contextTitle": "انتقال و دیسپاچینگ",
    "committeeScrutiny": "طرح در کمیته انتقال مصوب شد."
  }'
```

</div>

#### نمونه پاسخ (200 OK):
<div dir="ltr" style="text-align: left;">

```json
{
  "status": 200,
  "data": {
    "suggestionId": "sug-4892",
    "chunksCount": 4,
    "status": "APPROVED"
  }
}
```

</div>

---

### ۴.۳. بازنویسی و به‌روزرسانی کامل پیشنهاد (`PUT /suggestions/{suggestionId}`)

جهت جایگزینی کامل یک پیشنهاد موجود در پایگاه دانش به کار می‌رود. با فراخوانی این متد، بردارهای چانک‌های پیشین باطل و مجدداً بازتولید می‌شوند.

- **مسیر:** `/api/v1/suggestions/{suggestionId}`
- **متد:** `PUT`
- **فیلدهای الزامی بدنه:** `title`، `problem`، `solution`، `status`.

---

### ۴.۴. ویرایش جزئی مشخصات پیشنهاد (`PATCH /suggestions/{suggestionId}`)

زمانی استفاده می‌شود که تنها فیلد خاصی از پیشنهاد (مانند تغییر فیلد وضعیت `status` یا به‌روزرسانی شرح مصوبه کمیته `committeeScrutiny`) ویرایش شده و نیازی به بازتولید بردار کل فیلدها نباشد.

- **مسیر:** `/api/v1/suggestions/{suggestionId}`
- **متد:** `PATCH`

#### نمونه درخواست (cURL):
<div dir="ltr" style="text-align: left;">

```bash
curl -X PATCH "https://ai-assistant.tavanir.org.ir/api/v1/suggestions/sug-4892" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secure-secret-key-123" \
  -d '{
    "status": "EXECUTED",
    "committeeScrutiny": "پروژه در مهرماه ۱۴۰۳ با موفقیت به پایان رسید."
  }'
```

</div>

---

### ۴.۵. عملیات Soft Delete پیشنهاد و پاک‌سازی بردارها (`DELETE /suggestions/{suggestionId}`)

جهت Soft Delete یک پیشنهاد از سیستم و پاک‌سازی کامل بردارهای معنایی متناظر با آن از موتور جستجوی برداری استفاده می‌شود.

- **مسیر:** `/api/v1/suggestions/{suggestionId}`
- **متد:** `DELETE`

#### نمونه پاسخ (200 OK):
<div dir="ltr" style="text-align: left;">

```json
{
  "status": 200,
  "data": {
    "suggestionId": "sug-4892",
    "status": "DELETED"
  }
}
```

</div>

---

### ۴.۶. حذف دسته‌ای پیشنهادات (`POST /suggestions/bulk-delete`)

جهت پاک‌سازی گروهی رکوردهای نامعتبر یا قدیمی در یک تراکنش واحد به کار می‌رود.

- **مسیر:** `/api/v1/suggestions/bulk-delete`
- **متد:** `POST`

#### بدنه درخواست:
<div dir="ltr" style="text-align: left;">

```json
{
  "suggestionIds": ["sug-101", "sug-102", "sug-999"]
}
```

</div>

#### رفتارهای خروجی:
- **موفقیت کامل:** بازگشت کد `200 OK` با لیست موارد حذف‌شده.
- **موفقیت جزئی (Partial Success):** بازگشت کد **`207 Multi-Status`**؛ به این معنا که برخی شناسه‌ها با موفقیت حذف شده و برخی وجود نداشته یا با خطا روبرو شده‌اند:

<div dir="ltr" style="text-align: left;">

```json
{
  "status": 207,
  "data": [
    { "suggestionId": "sug-101", "status": "DELETED" }
  ],
  "errors": [
    {
      "status": 404,
      "code": "SUGGESTION_NOT_FOUND",
      "source": { "pointer": "/data/suggestionIds/1" }
    }
  ]
}
```

</div>

---

### ۴.۷. پایش سلامت سرویس (`GET /health`)

بررسی در دسترس بودن سرویس بدون نیاز به کلید دسترسی (عمومی).
- **مسیر:** `/health`
- **متد:** `GET`
- **پاسخ فعلی:** `{"status": "ok", "service": "tavanir-ai-assistant-v2", "mockMode": false}` (پاسخ مستقیم بررسی زنده‌بودن، بدون پوشش `data`)

---

### 4.8. Expand Suggestion (`POST /suggestions/expand-suggestion`)

Send one flat JSON object to `/api/v1/suggestions/expand-suggestion` with the existing `X-API-Key` and optional `X-Request-Id` headers:

```json
{"description": "Use temperature sensors to control cooling fans."}
```

`description` must be a nonblank strict string of at most 512 **model tokens**, not characters. Extra fields are rejected. Success is HTTP 200 with `{"status": 200, "data": {...}}`; `data` contains `title`, `currentProblem`, `solution`, `advantage`, and `disadvantage`. The server parses the LLM's marked plain text; clients receive JSON fields and should not split the HTTP response on `***`.

Invalid/over-limit descriptions return 422 `VALIDATION_ERROR`, missing input returns 422 `MISSING_REQUIRED_FIELD`, insufficient essential-section budget returns 422 `PROMPT_BUDGET_EXCEEDED`, malformed completions return 500 `GENERATION_FAILED`, and provider failures use the existing LLM codes. The current working-tree prompt uses translated labels while the parser requires English labels; consult the [Generation guide](../documentation/llm_generation_api.md) before live integration. This section documents the implemented contract and its open issue, not a verified live-model success.

---

## ۵. راهنمای مصرف و پردازش پاسخ تحلیل در سامانه مقصد

هنگام دریافت پاسخ از متد `/suggestions/analyze`، تیم توسعه سامانه نظام پیشنهادات باید دو گام اصلی زیر را در نرم‌افزار خود پیاده‌سازی کند:

### ۵.۱. واکشی اطلاعات تکمیلی از دیتابیس سامانه (Data Hydration by ID)
همان‌طور که در ساختار پاسخ مشخص است، سرویس هوش مصنوعی به منظور حفظ سرعت، سبک‌بودن حجم انتقال شبکه و تضمین محرمانگی اطلاعات اشخاص، **صرفاً آرایه‌ای از شناسه‌های رکوردهای مشابه (`similarExecutedIds`، `similarApprovedIds` و ...)** را بازمی‌گرداند.  
بنابراین سامانه نظام پیشنهادات باید:
1. با دریافت این شناسه‌ها، رکوردهای متناظر را مستقیماً از دیتابیس بومی خود واکشی (Query) کند.
2. مشخصات کامل پیشنهاد نظیر نام پیشنهاددهنده، تاریخچه تصمیمات، واحد سازمانی و کد پیگیری را در قالب کاردها یا جدول سوابق مرتبط به ارزیاب یا کاربر نمایش دهد.

### ۵.۲. تفسیر فیلد `analysis` در وضعیت فعلی
On the normal path, `analysis` is the model's validated decision-support answer. The existing no-usable-evidence branch returns diagnostic text instead and does not call the model. Display `uncertainty` with the answer, distinguish `citedSuggestionIds` from candidate IDs, and treat `groundingRatio` as coverage rather than confidence. Human review remains required. See the [Generation guide](../documentation/llm_generation_api.md), [test summary](../documentation/llm_generation_test_summary.md), and [remaining work](../next_steps.md).

---

## ۶. مدیریت خطا و دیکشنری کدهای اختصاصی (Error Handling)

در زمان بروز خطا، پاسخ ارسالی همواره آرایه‌ای به نام `errors` خواهد داشت:

<div dir="ltr" style="text-align: left;">

```json
{
  "errors": [
    {
      "status": 422,
      "code": "INVALID_SUGGESTION_STATUS",
      "source": { "pointer": "/data/status" }
    }
  ]
}
```

</div>

### جدول کدهای اختصاصی پرکاربرد:

| کد خطا (`code`) | وضعیت HTTP | مفهوم خطا | اقدام پیشنهادی در سامانه کلاینت |
| :--- | :---: | :--- | :--- |
| `API_KEY_MISSING` | 401 | هدر `X-API-Key` ارسال نشده است | بررسی تنظیمات اتصال و هدرهای کلاینت |
| `API_KEY_INVALID` | 401 | کلید معتبر نیست یا منقضی شده | بررسی و اصلاح کلید اختصاصی در سامانه |
| `VALIDATION_ERROR` | 422 | ساختار فیلدها معتبر نیست | تطبیق مقادیر با مدل داده مندرج در مستندات |
| `MISSING_REQUIRED_FIELD` | 422 | یکی از فیلدهای الزامی خالی ارسال شده | اعتبارسنجی اولیه فرم‌ها در سمت فرانت/بک |
| `INVALID_SUGGESTION_STATUS`| 422 | وضعیت ارسالی در جدول مجاز نیست | تبدیل وضعیت به شناسه‌های مجاز بخش ۲.۳ |
| `INVALID_SHAMSI_DATE` | 422 | فرمت تاریخ شمسی غیر از `YYYY/MM/DD` است | اصلاح قالب تاریخ و قرار دادن صفر ابتدای روز/ماه |
| `SUGGESTION_NOT_FOUND` | 404 | شناسه در پایگاه داده یافت نشد | بررسی صحت شناسه پیش از فراخوانی ویرایش یا حذف |
| `SUGGESTION_ALREADY_INGESTED` | 409 | شناسه تکراری است و قبلاً ایندکس شده | استفاده از متد ویرایش (`PUT`) به جای اینجست |
| `PROMPT_BUDGET_EXCEEDED` | 422 | طول متن از سقف مجاز توکن‌ها فراتر است | ترغیب کاربر به خلاصه‌سازی متن ورودی |
| `LLM_CONNECTION_FAILED` | 503 | Generation provider connection or timeout failure | Apply the caller's bounded retry policy and retain `X-Request-Id` for diagnostics. |
| `RATE_LIMITED` | 429 | تعداد درخواست‌های هم‌زمان بیش از سقف مجاز | کاهش نرخ فراخوانی‌ها و ایجاد صف میانی |
| `INTERNAL_ERROR` | 500 | خطای غیرمنتظره داخلی سرور | ثبت خطا در لاگ همراه با `X-Request-Id` |

---

## ۷. چک‌لیست پیاده‌سازی و اعتبارسنجی اتصال

- [ ] دریافت و پیکربندی امن کلید `X-API-Key` در لایه تنظیمات سامانه.
- [ ] آزمایش موفقیت‌آمیز استعلام از متد عمومی `/health`.
- [ ] اطمینان از نام‌گذاری کلیه فیلدهای ارسالی در قالب `camelCase`.
- [ ] اعمال جدول نگاشت وضعیت‌های بومی به مقادیر استاندارد `SuggestionStatus`.
- [ ] پیاده‌سازی منطق واکشی اطلاعات بر اساس شناسه‌های خروجی متد تحلیل (`similarExecutedIds` و ...).
- [ ] Display generated analysis as decision support with uncertainty and human review; handle the existing no-evidence diagnostic response explicitly.
- [ ] ارسال هدر `X-Request-Id` در تمامی درخواست‌ها جهت تسهیل خطایابی مشترک.
- [ ] پشتیبانی از هندلینگ وضعیت `207 Multi-Status` در متد حذف دسته‌ای.

</div>
