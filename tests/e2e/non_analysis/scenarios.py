"""Executable, independent oracles for the non-analysis HTTP checklist.

This module deliberately imports no production class.  The enum tables and short
golden fixtures are reviewed test data, not expectations calculated by the code
under test.  Every scenario runs against an owned TCP host and raw store reader.
"""

from __future__ import annotations

import json
import math
import string
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote


STATUS = {
    1: ("NOT_ACCEPTED", "عدم پذیرش"),
    2: ("REJECTED", "رد"),
    3: ("APPROVED", "مصوب"),
    4: ("PENDING", "در حال اجرا"),
    5: ("EXECUTED", "اجرا شده"),
}
COMMITTEE = {
    -10: ("SELECT_CONSULTANT_RETURN_FOR_CORRECTION", "انتخاب مشاور و برگشت جهت اصلاح"),
    -9: ("REJECTED_EXPERT_OPINION", "رد به دلیل رد کارشناسی"),
    -8: ("SEND_FOR_EXPERT_OPINION", "ارسال جهت اظهار نظر تخصصی"),
    -7: ("PILOT_EXECUTION", "اجرای پایلوت"),
    -6: ("OUT_OF_FRAMEWORK_REGULATION", "خارج از چارچوب ایین نامه نظام پیشنهاد ها"),
    -5: ("GENERAL_CONDITIONS_NOT_MET", "عدم احراز شرایط عمومی پذیرش"),
    -4: ("GENERALIZE_EXECUTION", "تعمیم اجرا"),
    -3: ("APPROVED_PRELIMINARY", "تایید"),
    -2: ("SEND_TO_UPPER_SECRETARIAT_COMMITTEE", "ارسال به کمیته دبیرخانه بالادستی"),
    -1: ("INVITE_TO_SESSION", "دعوت به جلسه"),
    0: ("APPROVED", "تایید"), 1: ("REJECTED", "رد"),
    2: ("SEND_TO_EXPERT", "ارسال به کارشناس"),
    3: ("RETURN_FOR_CORRECTION", "برگشت جهت اصلاح"),
    4: ("AWAITING_REVIEW", "منتظر بررسی"),
    5: ("ACCEPTED_AS_IDEA", "پذیرفته شده به عنوان ایده"),
    6: ("ACCEPTED_AS_EXECUTED_SUGGESTION", "پذیرفته شده به عنوان پیشنهاد اجراشده"),
    7: ("RETURN_TO_SECRETARIAT_CHANGE_COMMITTEE", "عودت به دبیرخانه جهت تغییر کمیته"),
    8: ("SEND_TO_EXPERT_GROUP", "ارسال به گروه کارشناسی"),
    9: ("ADMINISTRATIVE_OR_PERSONAL_REQUEST", "درخواستهای اداری و یا ملزومات شخصی می باشد ."),
    10: ("BEYOND_AUTHORITY_CONTRARY_TO_POLICIES", "خارج از حدود اختیارات و مغایر با سیاستها ، قوانین و اساسنامه شرکت"),
    11: ("NO_METHOD_OR_ADVANTAGES_SPECIFIED", "ارائه پیشنهاد بدون اعلام روش پیشنهادی و مزایای آن"),
    12: ("DUPLICATE_FROM_OTHER_PERSON", "قبلا از سوی پیشنهاد دهنده دیگر اعلام شده است . ( پیشنهاد  تکراری )"),
    13: ("CRITIQUE_OR_REMINDER_ONLY", "جنبه تذکر ، یادآوری و انتقاد از روش و استاندارد انجام کار است"),
    14: ("WITHIN_ROUTINE_DUTIES", "در حد وظایف جاری شرکت است"),
    15: ("EXECUTION_COST_EXCEEDS_BENEFITS", "هزینه اجرایی آن بیش از فوائد اجرای آن است"),
    16: ("PLANNED_IN_FUTURE_PROGRAMS", "در برنامه های آتی شرکت به صورت مستند پیش بینی شده است"),
    17: ("CURRENTLY_UNDERWAY", "در حال انجام است"),
    18: ("NOT_FEASIBLE", "غیر قابل اجرا میباشد"),
    19: ("NOT_BENEFICIAL_FOR_COMPANY", "به صرفه و صلاح شرکت نیست"),
    20: ("IS_A_COMPLAINT", "طرح شکایت است"),
    21: ("ON_COMPANY_AGENDA", "در دستور کار شرکت است"),
}
SECRETARIAT = {
    -2: ("SEND_TO_APPROVER", "ارسال به تایید کننده"),
    -1: ("EXPERT_OPINION", "اظهار نظر تخصصی"),
    0: ("OUT_OF_FRAMEWORK", "خارج از چهارچوب"),
    1: ("GENERAL_CONDITIONS_NOT_MET", "عدم احراز شرایط عمومی پذیرش"),
    2: ("REFER_TO_EXPERT", "ارجاع به کارشناسی"),
    3: ("REFER_TO_COMMITTEE", "ارجاع به کمیته"),
    4: ("ALREADY_SUBMITTED_BY_PERSON", "این پیشنهاد قبلا توسط شخصی ارائه شده است"),
    5: ("ALREADY_SUBMITTED_BY_NUMBER", "این پیشنهاد قبلا طی شماره ای ارائه شده است"),
    6: ("DUPLICATE", "این پیشنهاد تکراری است و قبلا ارائه شده است"),
    7: ("RETURNED_FOR_COMPLETION", "برگشت به پیشنهاددهنده جهت تکمیل"),
    8: ("NOT_A_SUGGESTION", "مورد طرح شده به دلایل ذیل پیشنهاد محسوب نمی شود"),
    9: ("REJECTED", "به دلایل ذیل پیشنهاد ارائه شده رد می باشد"),
    15: ("SEND_TO_EXPERT_GROUP", "ارسال به گروه کارشناسی"),
    16: ("REFER_TO_ANOTHER_SECRETARIAT", "ارجاع به دبیرخانه دیگر"),
    17: ("AUTO_REJECTED_EXPERT", "رد خودکار به دلیل کارشناسی"),
}
BASE = {
    "title": "بهینه سازی مصرف انرژی",
    "problem": "مصرف بالای انرژی در تجهیزات روشنایی",
    "solution": "نصب تجهیزات کم مصرف و کنترل هوشمند",
    "status": "APPROVED",
}
# Reviewed Persian orthography: the productive compound forms use ZWNJ.
# These golden strings are literal test data; no normalizer computes them.
BASE_GOLDEN = {
    "title": "بهینه\u200cسازی مصرف انرژی",
    "problem": "مصرف بالای انرژی در تجهیزات روشنایی",
    "solution": "نصب تجهیزات کم\u200cمصرف و کنترل هوشمند",
}
FULL = {
    **BASE, "committeeScrutiny": 0,
    "description": "طرح پس از بررسی فنی برای اجرا تایید شد",
    "shamsiDate": "۱۴۰۳/۰۲/۱۸", "contextTitle": "مدیریت توزیع برق",
    "secretariatScrutiny": -2,
    "secretariatComment": "بررسی اولیه انجام شد و پرونده کامل است",
}
CORE_FIELDS = ("title", "problem", "solution")
OPTIONAL_FIELDS = ("committeeScrutiny", "description", "shamsiDate", "contextTitle", "secretariatScrutiny", "secretariatComment")
SQL_FIELDS = {
    "committeeScrutiny": "committee_scrutiny", "description": "description",
    "shamsiDate": "shamsi_date", "contextTitle": "context_title",
    "secretariatScrutiny": "secretariat_scrutiny", "secretariatComment": "secretariat_comment",
    "tributaryScrutiny": "secretariat_scrutiny", "tributaryComment": "secretariat_comment",
}
NOISE = ("-", "--", "---", ".", "..", "...", "ندارد", "بدون شرح", "هیچ", "ثبت نشده", "موردی ندارد", "عدم وجود")
ENDPOINTS = ("ingest", "put", "patch", "delete", "bulk")
EDIT_ENDPOINTS = ("ingest", "put", "patch")


class ScenarioBlocked(RuntimeError):
    """An explicitly unmet capability; it is never a passing product outcome."""


@dataclass(frozen=True)
class Scenario:
    case_id: str
    variant_id: str
    profile: str
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)
    characterization: bool = False

    @property
    def id(self) -> str:
        return f"{self.case_id}/{self.variant_id}"


def _script_digits(value: str, script: str) -> str:
    digits = {"persian": "۰۱۲۳۴۵۶۷۸۹", "arabic": "٠١٢٣٤٥٦٧٨٩"}[script]
    return value.translate(str.maketrans("0123456789", digits))


def _variants() -> tuple[Scenario, ...]:
    cases: list[Scenario] = []

    def add(case: str, variant_id: str, operation: str, *, characterization: bool = False, **params: Any) -> None:
        cases.append(Scenario(case, variant_id, "real", operation, params, characterization=characterization))

    for case, route in (("HOST-01", "/"), ("HOST-02", "/health"), ("HOST-04", "/openapi.json"), ("HOST-05", "/scalar"), ("HOST-06", "/static/scalar.js")):
        add(case, "public", "host", path=route)
    add("HOST-06", "missing-static", "host", path="/static/missing-e2e.js", status=404)
    for route in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        add("HOST-07", route.strip("/").replace("/", "-"), "host", path=route)
    add("HOST-08", "unknown-api-route", "host", path="/api/v1/non-analysis-unknown", status=404, code="RESOURCE_NOT_FOUND")
    add("HOST-09", "unsupported-get", "host", path="/api/v1/suggestions/ingest", status=405, code="METHOD_NOT_ALLOWED")
    for endpoint in ENDPOINTS:
        add("HOST-10", endpoint, "trailing_slash", endpoint=endpoint)
    for method in ("POST", "PUT", "PATCH", "DELETE", "TRACE"):
        add("HOST-11", method.lower(), "cors", method=method, characterization=method == "TRACE")
    add("HOST-12", "persistent-clean-restart", "restart")

    for endpoint in ENDPOINTS:
        for case, value, label in (("API-01", None, "missing"), ("API-02", "wrong-ascii-key", "wrong"), ("API-03", "", "empty"), ("API-03", " ", "whitespace"), ("API-03", "pad-key", "padded-valid"), ("API-04", "capitalization", "capitalized"), ("API-04", "wrong-header", "wrong-header")):
            add(case, f"{endpoint}-{label}", "authentication", endpoint=endpoint, key=value)
        for value in ("duplicates", "duplicates-reversed", "non-ascii"):
            add("API-05", f"{endpoint}-{value}", "authentication", endpoint=endpoint, key=value, characterization=True)
        for invalid in (False, True):
            add("API-06", f"{endpoint}-{'invalid' if invalid else 'valid'}-body", "authentication", endpoint=endpoint, key=None, invalid_body=invalid, characterization=True)
        add("API-07", endpoint, "success_contract", endpoint=endpoint)
    for endpoint in EDIT_ENDPOINTS:
        add("API-08", f"{endpoint}-validation", "validation", endpoint=endpoint, field="unknown", value=1, code="VALIDATION_ERROR")
        add("API-08", f"{endpoint}-domain", "validation", endpoint=endpoint, field="title", value="abcd", code="INVALID_SUGGESTION_CONTENT")
    for kind in ("success", "auth", "validation", "bulk-partial"):
        default_endpoint = {"success": "ingest", "auth": "patch", "validation": "patch", "bulk-partial": "bulk"}[kind]
        for supplied in (False, True):
            add("API-11", f"{kind}-{'supplied' if supplied else 'generated'}", "request_id", kind=kind, supplied=supplied, endpoint=default_endpoint)
        for supplied in ("", "not-a-uuid"):
            add("API-12", f"{kind}-{'empty' if not supplied else 'malformed'}", "request_id", kind=kind, supplied=supplied, endpoint=default_endpoint, characterization=True)
        applicable = ENDPOINTS if kind in ("success", "auth") else (*EDIT_ENDPOINTS, "bulk") if kind == "validation" else ("bulk",)
        for endpoint in applicable:
            if endpoint == default_endpoint:
                continue
            for supplied, label in ((False, "generated"), (True, "supplied"), ("", "empty"), ("not-a-uuid", "malformed")):
                add("API-11" if type(supplied) is bool else "API-12", f"{endpoint}-{kind}-{label}", "request_id", endpoint=endpoint, kind=kind, supplied=supplied, characterization=type(supplied) is str)
    # DELETE has no request-body validation schema; lookup failure exercises its
    # error response category without inventing a schema rejection requirement.
    for supplied, label in ((False, "generated"), (True, "supplied"), ("", "empty"), ("not-a-uuid", "malformed")):
        add("API-11" if type(supplied) is bool else "API-12", f"delete-lookup-{label}", "request_id", endpoint="delete", kind="lookup", supplied=supplied, characterization=type(supplied) is str)

    for endpoint in (*EDIT_ENDPOINTS, "bulk"):
        for label, body in (("missing", "__absent__"), ("null", None), ("array", []), ("string", "text"), ("number", 2)):
            add("VAL-01", f"{endpoint}-{label}", "raw_validation", endpoint=endpoint, body=body)
        for label, body in (("malformed", b'{"title":}'), ("truncated", b'{"title":"abc'), ("invalid-utf8", b'{"title":"\xff"}')):
            add("VAL-02", f"{endpoint}-{label}", "raw_validation", endpoint=endpoint, body=body, raw=True, characterization=label == "invalid-utf8")
    for endpoint in EDIT_ENDPOINTS:
        add("VAL-03", endpoint, "validation", endpoint=endpoint, wrapper=True)
        for name in ("unknown", "version", "isDeleted", "committeeScrutinyId", "secretariatScrutinyId"):
            add("VAL-04", f"{endpoint}-{name}", "validation", endpoint=endpoint, field=name, value=1, code="VALIDATION_ERROR")
        if endpoint != "patch":
            for name in ((*CORE_FIELDS, "status", "suggestionId") if endpoint == "ingest" else (*CORE_FIELDS, "status")):
                add("VAL-05", f"{endpoint}-{name}", "validation", endpoint=endpoint, field=name, omit=True, code="MISSING_REQUIRED_FIELD")
            add("VAL-05", f"{endpoint}-multiple-missing", "validation", endpoint=endpoint, omit_all=True, code="MISSING_REQUIRED_FIELD")
        for name in CORE_FIELDS:
            for label, value in (("null", None), ("number", 11), ("boolean", True), ("array", []), ("object", {})):
                if endpoint == "patch" and value is None:
                    continue
                add("VAL-06", f"{endpoint}-{name}-{label}", "validation", endpoint=endpoint, field=name, value=value, code="VALIDATION_ERROR")
            for label, value in (("empty", ""), ("whitespace", "   ")):
                add("VAL-07", f"{endpoint}-{name}-{label}", "validation", endpoint=endpoint, field=name, value=value, code="INVALID_SUGGESTION_CONTENT" if endpoint == "ingest" and value else "VALIDATION_ERROR")
            for length in (1, 4, 5):
                add("VAL-08", f"{endpoint}-{name}-length-{length}", "validation", endpoint=endpoint, field=name, value="abcde"[:length], status=201 if endpoint == "ingest" and length == 5 else 200 if length == 5 else 422, code=None if length == 5 else "INVALID_SUGGESTION_CONTENT", expected={name: "abcde"} if length == 5 else {})
            for number, value in enumerate((*NOISE, "اَََََََََ")):
                add("VAL-09", f"{endpoint}-{name}-noise-{number}", "validation", endpoint=endpoint, field=name, value=value, code="INVALID_SUGGESTION_CONTENT")
        for number, (name, title) in STATUS.items():
            reps = {"integer": number, "ascii": str(number), "persian-digits": _script_digits(str(number), "persian"), "arabic-digits": _script_digits(str(number), "arabic"), "enum": name, "title": title}
            for label, value in reps.items():
                for padded in (False, True) if isinstance(value, str) else (False,):
                    add("VAL-10", f"{endpoint}-{number}-{label}{'-padded' if padded else ''}", "validation", endpoint=endpoint, field="status", value=f" {value} " if padded else value, status=201 if endpoint == "ingest" else 200, expected={"status_id": number})
        for label, value in (("zero", 0), ("six", 6), ("negative", -1), ("unknown-name", "UNKNOWN"), ("unknown-title", "نامعلوم"), ("lowercase", "approved"), ("empty", ""), ("whitespace", " "), ("float", 3.1), ("object", {}), ("array", []), ("null", None)):
            if endpoint == "patch" and value is None:
                continue
            add("VAL-11", f"{endpoint}-{label}", "validation", endpoint=endpoint, field="status", value=value, code="INVALID_SUGGESTION_STATUS")
        for value in (True, False):
            add("VAL-12", f"{endpoint}-status-{str(value).lower()}", "validation", endpoint=endpoint, field="status", value=value, status=422, code="INVALID_SUGGESTION_STATUS")
            for name in ("committeeScrutiny", "secretariatScrutiny"):
                add("VAL-12", f"{endpoint}-{name}-{str(value).lower()}", "validation", endpoint=endpoint, field=name, value=value, status=422, code="INVALID_COMMITTEE_SCRUTINY" if name == "committeeScrutiny" else "INVALID_SECRETARIAT_SCRUTINY")
        for field_name, table in (("committeeScrutiny", COMMITTEE), ("secretariatScrutiny", SECRETARIAT)):
            for number, (name, title) in table.items():
                reps = {"integer": number, "ascii": str(number), "persian-digits": _script_digits(str(number), "persian"), "arabic-digits": _script_digits(str(number), "arabic"), "enum": name, "title": title, "arabic-letters": title.replace("ی", "ي").replace("ک", "ك"), "half-spaces": title.replace(" ", "\u200c")}
                for label, value in reps.items():
                    expected_code = 0 if field_name == "committeeScrutiny" and number == -3 and label in ("title", "arabic-letters", "half-spaces") else number
                    add("VAL-13", f"{endpoint}-{field_name}-{number}-{label}", "validation", endpoint=endpoint, field=field_name, value=value, status=201 if endpoint == "ingest" else 200, expected={SQL_FIELDS[field_name] + "_id": expected_code, SQL_FIELDS[field_name]: table[expected_code][1]})
            invalid = (-11, 22, "UNKNOWN", 1.5, [], {}) if field_name == "committeeScrutiny" else (-3, 10, 14, 18, "UNKNOWN", 1.5, [], {})
            for index, value in enumerate(invalid):
                add("VAL-15", f"{endpoint}-{field_name}-invalid-{index}", "validation", endpoint=endpoint, field=field_name, value=value, code="INVALID_COMMITTEE_SCRUTINY" if field_name == "committeeScrutiny" else "INVALID_SECRETARIAT_SCRUTINY")
        for label, value in (("title", "تایید"), ("name", "APPROVED"), ("zero", 0), ("preliminary", -3)):
            add("VAL-14", f"{endpoint}-{label}", "validation", endpoint=endpoint, field="committeeScrutiny", value=value, status=201 if endpoint == "ingest" else 200, expected={"committee_scrutiny_id": -3 if value == -3 else 0}, preserve_scrutiny=True)
        for name in OPTIONAL_FIELDS:
            for label, value in (("omitted", "__omit__"), ("null", None), ("empty", ""), ("whitespace", "   ")):
                add("VAL-16", f"{endpoint}-{name}-{label}", "optional", endpoint=endpoint, field=name, value=value)
        for label, date in (("ascii", "1403/02/18"), ("persian", "۱۴۰۳/۰۲/۱۸"), ("arabic", "١٤٠٣/٠٢/١٨"), ("padded", " 1403/02/18 ")):
            add("VAL-17", f"{endpoint}-{label}", "validation", endpoint=endpoint, field="shamsiDate", value=date, status=201 if endpoint == "ingest" else 200, expected={"shamsi_date": "1403/02/18"})
        for label, value in (("separator", "1403-02-18"), ("unpadded-month", "1403/2/18"), ("unpadded-day", "1403/02/8"), ("digits", "140/02/18"), ("year-low", "0999/01/01"), ("year-high", "5000/01/01"), ("month-zero", "1403/00/01"), ("month-high", "1403/13/01"), ("day-zero", "1403/01/00"), ("day-high", "1403/01/32"), ("suffix", "1403/01/01text")):
            add("VAL-18", f"{endpoint}-{label}", "validation", endpoint=endpoint, field="shamsiDate", value=value, code="INVALID_SHAMSI_DATE", pointer="/data/date")
        for value in ("1402/07/31", "1402/12/30"):
            add("VAL-19", f"{endpoint}-{value.replace('/', '-')}", "validation", endpoint=endpoint, field="shamsiDate", value=value, status=422, code="INVALID_SHAMSI_DATE", pointer="/data/date")
        for label, value in (("number", 14030218), ("boolean", True), ("array", []), ("object", {})):
            add("VAL-20", f"{endpoint}-{label}", "validation", endpoint=endpoint, field="shamsiDate", value=value, code="INVALID_SHAMSI_DATE")
        for field_name, value in (("tributaryScrutiny", -2), ("tributaryComment", "abcdefghijklmnop")):
            add("VAL-21", f"{endpoint}-{field_name}", "validation", endpoint=endpoint, field=field_name, value=value, status=201 if endpoint == "ingest" else 200, expected={SQL_FIELDS[field_name] + "_id": -2} if field_name.endswith("Scrutiny") else {SQL_FIELDS[field_name]: value})
        for side in ("Scrutiny", "Comment"):
            for label, canonical, legacy, status in (("both-valid", 0 if side == "Scrutiny" else "abcdef", -2 if side == "Scrutiny" else "ghijkl", 422), ("both-blank", "", "", 422), ("legacy-null", -2 if side == "Scrutiny" else "abcdefghijklmnop", None, 201 if endpoint == "ingest" else 200), ("canonical-null-camel", None, -2 if side == "Scrutiny" else "abcdefghijklmnop", 422), ("canonical-null-snake", None, -2 if side == "Scrutiny" else "abcdefghijklmnop", 201 if endpoint == "ingest" else 200)):
                add("VAL-22", f"{endpoint}-{side}-{label}", "aliases", endpoint=endpoint, side=side, canonical=canonical, legacy=legacy, snake=label.endswith("snake"), status=status, characterization=True)
        add("VAL-22", f"{endpoint}-cross-pair", "validation", endpoint=endpoint, extra={"secretariatScrutiny": -2, "tributaryComment": "abcdefghijklmnop"}, status=201 if endpoint == "ingest" else 200, expected={"secretariat_scrutiny_id": -2, "secretariat_comment": "abcdefghijklmnop"})
        for style in ("snake", "mixed", "duplicate-alias"):
            add("VAL-23", f"{endpoint}-{style}", "naming", endpoint=endpoint, style=style, characterization=True)
        for name in ("description", "contextTitle", "secretariatComment"):
            for label, value in (("number", 7), ("boolean", True), ("array", []), ("object", {})):
                add("VAL-24", f"{endpoint}-{name}-{label}", "validation", endpoint=endpoint, field=name, value=value, code="VALIDATION_ERROR")
            add("VAL-24", f"{endpoint}-{name}-trimmed", "validation", endpoint=endpoint, field=name, value="  abcdefghijklmnop  ", status=201 if endpoint == "ingest" else 200, expected={SQL_FIELDS[name]: "abcdefghijklmnop"})
        for length in (255, 256):
            add("VAL-25", f"{endpoint}-context-{length}", "validation", endpoint=endpoint, field="contextTitle", value=(string.ascii_lowercase * 10)[:length], status=201 if endpoint == "ingest" else 200, expected={"context_title": (string.ascii_lowercase * 10)[:length]})
        for label, media in (("charset", "application/json; charset=utf-8"), ("plus-json", "application/vnd.api+json"), ("absent", None), ("text", "text/plain"), ("form", "application/x-www-form-urlencoded"), ("multipart", "multipart/form-data; boundary=e2e")):
            add("VAL-30", f"{endpoint}-{label}", "media", endpoint=endpoint, media=media, accepted=label in ("charset", "plus-json", "absent"), characterization=True)
        for variant in ("duplicate-property", "escaped-unicode", "literal-unicode", "large-valid", "large-invalid"):
            add("VAL-31", f"{endpoint}-{variant}", "json_characterization", endpoint=endpoint, variant=variant, characterization=True)
    for length in (1, 64, 65):
        add("VAL-25", f"ingest-id-{length}", "identity", length=length)
    for variant in ("persian", "case-distinct", "trimmed", "leading-zero", "digit-script"):
        add("VAL-26" if variant in ("persian", "case-distinct", "trimmed") else "VAL-29", variant, "identity", variant=variant)
    for label, value in (("empty", ""), ("whitespace", " "), ("null", None), ("number", 2), ("boolean", True), ("array", []), ("object", {})):
        add("VAL-29", f"ingest-{label}", "validation", endpoint="ingest", field="suggestionId", value=value, code="VALIDATION_ERROR")
    for variant in ("space", "special", "slash", "missing-segment", "long"):
        add("VAL-27", variant, "path_identity", variant=variant, characterization=True)
    for endpoint in ("put", "patch", "delete"):
        for side in ("leading", "trailing", "surrounding"):
            add("VAL-26", f"{endpoint}-{side}-path-space", "exact_path_whitespace", endpoint=endpoint, side=side)
    add("VAL-28", "query-and-delete-body", "delete_incidental", characterization=True)
    for word in ("ingest", "bulk-delete"):
        for endpoint in ("put", "patch", "delete"):
            add("VAL-32", f"{word}-{endpoint}", "route_word", word=word, endpoint=endpoint)

    for case, variant in (("ING-01", "minimal"), ("ING-02", "full")):
        add(case, variant, "ingestion", variant=variant)
    for variant in ("committee-only", "secretariat-only", "both", "scrutiny-only"):
        add("ING-03", variant, "ingestion", variant=variant)
    for side in ("description", "secretariatComment"):
        for length in (14, 15, 16):
            add("ING-04", f"{side}-{length}", "ingestion", variant="comment-length", field=side, length=length)
        for index, noise in enumerate(NOISE):
            add("ING-04", f"{side}-noise-{index}", "ingestion", variant="comment-noise", field=side, value=noise)
        for normalization in ("diacritic", "emoji"):
            add("ING-04", f"{side}-raw15-normalized14-{normalization}", "ingestion", variant="normalized-comment-threshold", field=side, normalization=normalization)
    for context in (None, "abcd", "abcde", "abcdef"):
        add("ING-05", f"context-{len(context) if context else 0}", "ingestion", variant="context", context=context)
    for variant in ("paragraph", "newline", "persian-punctuation", "word-boundaries"):
        add("ING-06", variant, "ingestion", variant="long", separator=variant)
    for variant in ("long-title", "long-evaluation", "unbroken-problem", "unbroken-solution"):
        add("ING-07", variant, "ingestion", variant=variant, characterization=True)
    for variant in ("arabic-letters", "diacritics", "emoji", "repeated", "zwnj", "digits", "whitespace"):
        add("ING-08", variant, "ingestion", variant="unicode", unicode_variant=variant)
    for variant in ("heading", "list", "checklist", "code", "table", "url", "link", "math", "decimal"):
        add("ING-09", variant, "ingestion", variant="markdown", markdown_variant=variant)
    for variant in ("stopwords", "bm25-max-minus-one", "bm25-max", "bm25-max-plus-one"):
        add("ING-10", variant, "ingestion", variant=variant)
    for case, variant in (("ING-11", "identical-active"), ("ING-12", "different-active"), ("ING-12", "deleted"), ("ING-13", "domain-invalid"), ("ING-13", "schema-invalid")):
        add(case, variant, "duplicate", variant=variant)
    for state in ("active", "staging", "deprecated", "mixed"):
        add("ING-14", state, "residual_ingestion", state=state)
    for boundary in ("qdrant", "embedding"):
        for delta in (0, 1):
            add("ING-15", f"{boundary}-boundary-plus-{delta}", "ingestion", variant="batch-boundary", boundary=boundary, delta=delta)
    add("ING-16", "independent-enums", "ingestion", variant="independent-enums")
    add("ING-17", "literal-placeholder-and-protected-code", "ingestion", variant="placeholder", characterization=True)
    for side in ("committee", "secretariat"):
        for other in ("short", "noise"):
            add("ING-18", f"{side}-substantive-other-{other}", "ingestion", variant="one-substantive", side=side, other=other)
    for variant in ("orphan-validation-failure", "sql-without-points"):
        add("ING-F14", variant, "residual_ingestion", variant=variant)

    for case, variant in (("PUT-01", "full"), ("PUT-02", "omitted"), ("PUT-03", "null"), ("PUT-03", "blank"), ("PUT-04", "deleted"), ("PUT-04", "deleted-residual"), ("PUT-05", "missing"), ("PUT-09", "grow"), ("PUT-09", "shrink"), ("PUT-10", "identical-twice"), ("PUT-11", "modern"), ("PUT-11", "legacy")):
        add(case, variant, "put", variant=variant)
    for value in ("__omit__", None, "__match__", "__padded__", "__different__", "", " "):
        add("PUT-07" if value in ("", " ") else "PUT-06", f"body-id-{str(value)}", "put", variant="body-id", value=value, characterization=value in ("", " "))
    for name in ("status", "committeeScrutiny", "secretariatScrutiny", "shamsiDate", "contextTitle"):
        add("PUT-08", name, "put", variant="metadata", field=name)
    for name in CORE_FIELDS:
        add("PAT-01", name, "patch", variant="single-field", field=name)
    for name in ("status", *OPTIONAL_FIELDS):
        add("PAT-02", name, "patch", variant="single-field", field=name)
    for name in (*CORE_FIELDS, "status", *OPTIONAL_FIELDS):
        add("PAT-03", name, "patch", variant="ignored-null", field=name)
    for variant in ("empty", "all-null"):
        add("PAT-04", variant, "patch", variant=variant)
    for spelling in ("suggestionId", "suggestion_id"):
        for value in ("matching", "different", None, ""):
            add("PAT-05", f"{spelling}-{value}", "patch", variant="forbidden-id", field=spelling, value=value)
    for name in CORE_FIELDS:
        for label, value in (("empty", ""), ("blank", " "), ("short", "abcd"), ("noise", "ندارد")):
            add("PAT-06", f"{name}-{label}", "patch", variant="invalid-core", field=name, value=value)
    for name in OPTIONAL_FIELDS:
        for value in ("", " "):
            add("PAT-07", f"{name}-{'empty' if not value else 'blank'}", "patch", variant="blank-noop", field=name, value=value, characterization=True)
            add("PAT-08", f"{name}-{'empty' if not value else 'blank'}", "patch", variant="blank-overlay", field=name, value=value)
    for variant in ("missing", "deleted"):
        add("PAT-09", variant, "patch", variant=variant)
    for variant in ("comment-only", "scrutiny-only", "preserve-independent"):
        add("PAT-10", variant, "patch", variant=variant)
    for length in (14, 15, 16):
        for side in ("description", "secretariatComment"):
            add("PAT-11", f"{side}-{length}", "patch", variant="threshold", field=side, length=length)
    for side in ("description", "secretariatComment"):
        for normalization in ("diacritic", "emoji"):
            add("PAT-11", f"{side}-raw15-normalized14-{normalization}", "patch", variant="normalized-comment-threshold", field=side, normalization=normalization)
    add("PAT-11", "long-to-short", "patch", variant="shrink")
    add("PAT-12", "multi-field", "patch", variant="multiple")
    add("PAT-13", "same-value-twice", "patch", variant="identical-twice")
    for variant in ("modern", "legacy", "committee-ambiguity", "conflict"):
        add("PAT-14", variant, "patch", variant=variant)
    add("PAT-15", "valid-and-invalid-overlays", "patch", variant="atomic-validation")

    for case, variant in (("DEL-01", "full"), ("DEL-02", "zero-points"), ("DEL-02", "many"), ("DEL-02", "mixed"), ("DEL-03", "repeat"), ("DEL-04", "missing"), ("DEL-04", "missing-orphans"), ("DEL-05", "deleted-orphans"), ("DEL-14", "restore-put"), ("DEL-14", "reject-patch"), ("DEL-14", "reject-ingest")):
        add(case, variant, "delete", variant=variant, characterization=case == "DEL-05")
    for case, variant in (("BULK-01", "one"), ("BULK-02", "several"), ("BULK-02", "hundred"), ("BULK-03", "active-and-deleted"), ("BULK-03", "all-deleted"), ("BULK-05", "all-missing"), ("BULK-12", "case-distinct"), ("BULK-13", "trimmed"), ("BULK-14", "repeat-all-success"), ("BULK-14", "repeat-partial"), ("BULK-16", "deleted-orphans"), ("BULK-18", "hundred-latency")):
        add(case, variant, "bulk", variant=variant, characterization=case in ("BULK-16", "BULK-18"))
    for position in (0, 1, 2):
        add("BULK-04", f"missing-index-{position}", "bulk", variant="partial", position=position)
        add("BULK-13", f"trimmed-missing-index-{position}", "bulk", variant="trimmed-partial", position=position)
    for variant, body in (("missing", {}), ("null", {"suggestionIds": None}), ("empty", {"suggestionIds": []}), ("hundred-one", {"suggestionIds": [f"invalid-{i}" for i in range(101)]}), ("string", {"suggestionIds": "id"}), ("object", {"suggestionIds": {}}), ("extra", {"suggestionIds": ["__existing__"], "unknown": 1})):
        add("BULK-10", variant, "bulk_invalid", body=body, code="MISSING_REQUIRED_FIELD" if variant == "missing" else "VALIDATION_ERROR")
    for label, value in (("null", None), ("number", 1), ("boolean", True), ("object", {}), ("empty", ""), ("whitespace", " ")):
        add("BULK-11", label, "bulk_invalid", body={"suggestionIds": ["__existing__", value]}, code="VALIDATION_ERROR")
    for variant in ("duplicate", "duplicate-trimmed"):
        add("BULK-12", variant, "bulk_invalid", duplicate=variant, code="VALIDATION_ERROR")
    for case, variant in (("FLOW-01", "full-lifecycle"), ("FLOW-02", "put"), ("FLOW-02", "patch"), ("FLOW-02", "delete"), ("FLOW-02", "bulk"), ("FLOW-03", "validation-and-auth-each-stage"), ("FLOW-15", "persistent-restart")):
        add(case, variant, "flow", variant=variant)
    assert len({case.id for case in cases}) == len(cases), "duplicate scenario identity"
    return tuple(cases)


NORMAL_SCENARIOS = _variants()


def _endpoint(endpoint: str, suggestion_id: str) -> tuple[str, str]:
    path = f"/api/v1/suggestions/{quote(suggestion_id, safe='')}"
    return {
        "ingest": ("POST", "/api/v1/suggestions/ingest"),
        "put": ("PUT", path), "patch": ("PATCH", path), "delete": ("DELETE", path),
        "bulk": ("POST", "/api/v1/suggestions/bulk-delete"),
    }[endpoint]


def _body(endpoint: str, suggestion_id: str, *, full: bool = False) -> dict[str, Any] | None:
    if endpoint == "delete":
        return None
    if endpoint == "bulk":
        return {"suggestionIds": [suggestion_id]}
    if endpoint == "patch":
        return {"title": "عنوان جدید برای کاهش مصرف انرژی"}
    return {**(FULL if full else BASE), **({"suggestionId": suggestion_id} if endpoint == "ingest" else {})}


def _observe(harness: Any, name: str, data: Any) -> None:
    if hasattr(harness, "observe"):
        harness.observe(name, data)


def assert_error(response: Any, status: int, code: str | None = None, pointer: str | None = None) -> dict[str, Any]:
    assert response.status_code == status, f"HTTP {response.status_code}, expected {status}: {response.text}"
    result = response.json()
    assert "data" not in result, result
    errors = result.get("errors")
    assert isinstance(errors, list) and errors, result
    for error in errors:
        assert type(error["status"]) is int
        assert isinstance(error.get("code"), str) and error["code"]
        if error.get("source") is not None:
            assert error["source"].get("pointer", "").startswith("/"), error
    if code is not None:
        assert any(error["code"] == code for error in errors), result
    if pointer is not None:
        assert any((error.get("source") or {}).get("pointer") == pointer for error in errors), result
    return result


def assert_consistent(harness: Any, suggestion_id: str, response: Any, *, previous: dict[str, Any] | None = None, expected: dict[str, Any] | None = None, count: int | None = None) -> dict[str, Any]:
    """Raw SQL/vector consistency plus fixture expectations, for normal successes."""
    status = 201 if previous is None else 200
    assert response.status_code == status, f"HTTP {response.status_code}: {response.text}"
    result = response.json()
    assert result["status"] == status and type(result["status"]) is int, result
    data = result["data"]
    assert data["suggestionId"] == suggestion_id
    assert data["status"] == ("CREATED" if previous is None else "UPDATED")
    assert set(data) == ({"suggestionId", "chunksCount", "status"} if previous is None else {"suggestionId", "chunksCount", "version", "status"}), data
    snapshot = harness.snapshot(suggestion_id)
    row, points = snapshot["sql"], snapshot["points"]
    assert row is not None and row["id"] == suggestion_id and row["is_deleted"] is False
    assert row["created_at"] and row["updated_at"]
    assert row["version"] == (1 if previous is None else previous["sql"]["version"] + 1)
    if previous is not None:
        assert row["created_at"] == previous["sql"]["created_at"]
        assert data["version"] == row["version"]
        assert {str(point["id"]) for point in points}.isdisjoint(str(point["id"]) for point in previous["points"]), "superseded point IDs survive"
    for key, value in (expected or {}).items():
        assert row[key] == value, f"{key}: {row[key]!r} != {value!r}"
    assert len(points) == data["chunksCount"] and points
    if count is not None:
        assert len(points) == count
    ids = [str(point["id"]) for point in points]
    assert len(ids) == len(set(ids))
    cfg = harness.config
    by_type: dict[str, list[dict[str, Any]]] = {}
    for point in points:
        payload = point["payload"]
        assert payload["parent_id"] == suggestion_id
        assert str(point["id"]) == payload["chunk_id"]
        uuid.UUID(payload["chunk_id"])
        assert payload["chunk_status"] == "active", f"non-active final point: {payload}"
        assert payload["status"] == STATUS[row["status_id"]][1]
        assert "parent_content" not in payload and payload.get("version") == row["version"]
        for sql_name, payload_name in (("context_title", "context_title"), ("shamsi_date", "date"), ("committee_scrutiny", "committee_scrutiny"), ("committee_scrutiny_id", "committee_scrutiny_id"), ("secretariat_scrutiny", "secretariat_scrutiny"), ("secretariat_scrutiny_id", "secretariat_scrutiny_id")):
            if row[sql_name] is None:
                assert payload_name not in payload, f"null metadata not omitted: {payload_name}"
            else:
                assert payload[payload_name] == row[sql_name]
        assert all("_" in name or name.islower() for name in payload), payload
        vector = point.get("vector", point.get("vectors"))
        assert isinstance(vector, dict), point
        dense = vector[cfg.dense_name]
        assert len(dense) == cfg.dense_dimension
        assert all(isinstance(value, (int, float)) and math.isfinite(value) for value in dense)
        sparse = vector[cfg.sparse_name]
        assert len(sparse["indices"]) == len(sparse["values"])
        assert len(set(sparse["indices"])) == len(sparse["indices"])
        assert all(type(index) is int and index >= 0 for index in sparse["indices"])
        assert all(math.isfinite(value) for value in sparse["values"])
        by_type.setdefault(payload["chunk_type"], []).append(payload)
    assert set(by_type).issubset({"title", "problem", "solution", "evaluation"})
    assert len(by_type.get("title", [])) == 1
    title = by_type["title"][0]
    assert title["sub_index"] == 0
    context = row["context_title"]
    expected_title = f"حوزه: {context.strip()} | عنوان: {row['title'].strip()}" if context and len(context.strip()) >= 5 and context.strip() not in NOISE else row["title"].strip()
    assert title["content"] == expected_title
    for name in ("problem", "solution"):
        chunks = sorted(by_type.get(name, []), key=lambda chunk: chunk["sub_index"])
        assert chunks and [chunk["sub_index"] for chunk in chunks] == list(range(len(chunks)))
        for chunk in chunks:
            assert chunk["content"] in row[name], f"field contamination: {chunk}"
        if len(row[name]) <= getattr(cfg, "max_chunk_chars", 1500):
            assert len(chunks) == 1 and chunks[0]["content"] == row[name].strip()
    substantive = lambda value: bool(value and len(value.strip()) >= 15 and value.strip() not in NOISE)
    expect_eval = substantive(row["description"]) or substantive(row["secretariat_comment"])
    assert len(by_type.get("evaluation", [])) == int(expect_eval)
    if expect_eval:
        evaluation = by_type["evaluation"][0]
        assert evaluation["sub_index"] == 0
        for key, label in (("description", "توضیحات مصوبه"), ("secretariat_comment", "نظر دبیرخانه")):
            if substantive(row[key]):
                assert f"{label}: {row[key].strip()}" in evaluation["content"]
            else:
                assert f"{label}:" not in evaluation["content"]
    return snapshot


def _create(harness: Any, label: str, *, full: bool = True, fields: dict[str, Any] | None = None, exact_id: str | None = None) -> tuple[str, dict[str, Any]]:
    suggestion_id = exact_id or harness.new_id(label)
    if exact_id is not None:
        harness.register_id(exact_id)
    payload = {**(FULL if full else BASE), **(fields or {}), "suggestionId": suggestion_id}
    response = harness.request("POST", "/api/v1/suggestions/ingest", json=payload)
    expected = {key: value for key, value in BASE_GOLDEN.items() if key not in (fields or {})}
    expected["status_id"] = 3
    if full:
        expected.update({"shamsi_date": "1403/02/18", "context_title": FULL["contextTitle"], "committee_scrutiny_id": 0, "secretariat_scrutiny_id": -2})
        expected = {key: value for key, value in expected.items() if key not in {SQL_FIELDS.get(field, field) for field in fields or {}}}
    return suggestion_id, assert_consistent(harness, suggestion_id, response, expected=expected)


def _setup(harness: Any, endpoint: str, label: str, *, full: bool = True) -> tuple[str, dict[str, Any]]:
    if endpoint == "ingest":
        suggestion_id = harness.new_id(label)
        return suggestion_id, harness.snapshot(suggestion_id)
    return _create(harness, label, full=full)


def _assert_unchanged(harness: Any, suggestion_id: str, before: dict[str, Any]) -> None:
    assert harness.snapshot(suggestion_id) == before, f"rejected/no-op request changed stores for {suggestion_id}"


def _request(harness: Any, endpoint: str, suggestion_id: str, body: Any, **kwargs: Any) -> Any:
    method, path = _endpoint(endpoint, suggestion_id)
    return harness.request(method, path, json=body, **kwargs)


def _assert_delete(harness: Any, suggestion_id: str, response: Any, before: dict[str, Any]) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    assert response.json() == {"status": 200, "data": {"suggestionId": suggestion_id, "status": "DELETED"}}
    after = harness.snapshot(suggestion_id)
    assert after["sql"]["is_deleted"] is True
    assert after["sql"]["version"] == before["sql"]["version"] + (0 if before["sql"]["is_deleted"] else 1)
    for key in before["sql"]:
        if key not in ("version", "is_deleted", "updated_at"):
            assert after["sql"][key] == before["sql"][key], key
    if before["sql"]["is_deleted"]:
        assert after["sql"] == before["sql"]
    assert after["points"] == [], "successful deletion left orphan vectors"
    return after


def execute_scenario(harness: Any, scenario: Scenario) -> None:
    """Run one manifest variant; assertions are never retried until green."""
    params = scenario.parameters
    operation = globals().get(f"_run_{scenario.operation}")
    if operation is None:
        raise ScenarioBlocked(f"No executable implementation for {scenario.operation}")
    started = time.monotonic()
    operation(harness, **params)
    _observe(harness, "scenario", {"case_id": scenario.case_id, "variant_id": scenario.variant_id, "characterization": scenario.characterization, "duration_seconds": time.monotonic() - started})


def _run_host(harness: Any, path: str, status: int = 200, code: str | None = None) -> None:
    response = harness.request("GET", path, auth=False)
    assert response.status_code == status, response.text
    if code:
        assert_error(response, status, code)
    elif path == "/":
        assert response.json() == {"service": "Tavanir AI Assistant V2", "version": "2.0.0", "mockMode": False, "documentation": "/scalar or /docs", "health": "/health"}
    elif path == "/health":
        assert response.json() == {"status": "ok", "service": "tavanir-ai-assistant-v2", "mockMode": False}
    elif path == "/openapi.json":
        spec = response.json()
        paths = spec["paths"]
        assert "post" in paths["/api/v1/suggestions/ingest"]
        assert "post" in paths["/api/v1/suggestions/bulk-delete"]
        for method in ("put", "patch", "delete"):
            assert method in paths["/api/v1/suggestions/{suggestionId}"]
        schemes = spec["components"]["securitySchemes"]
        assert any(s.get("type") == "apiKey" and s.get("in") == "header" and s.get("name") == harness.config.api_header for s in schemes.values())
        schemas = spec["components"]["schemas"]
        for name in ("IngestSuggestionRequest", "UpdateSuggestionRequest", "PatchSuggestionRequest"):
            assert "committeeScrutiny" in schemas[name]["properties"]
            assert "secretariatComment" in schemas[name]["properties"]
        for path_name, method, success in (("/api/v1/suggestions/ingest", "post", "201"), ("/api/v1/suggestions/{suggestionId}", "put", "200"), ("/api/v1/suggestions/{suggestionId}", "patch", "200"), ("/api/v1/suggestions/{suggestionId}", "delete", "200"), ("/api/v1/suggestions/bulk-delete", "post", "200")):
            assert success in paths[path_name][method]["responses"]
    elif path.startswith("/static/"):
        if status == 200:
            assert response.content and "javascript" in response.headers["content-type"]
    else:
        assert "text/html" in response.headers["content-type"] and "<html" in response.text.lower()
        if path == "/scalar":
            assert "/openapi.json" in response.text and "/static/scalar.js" in response.text
    if status == 405:
        assert response.headers.get("allow")


def _run_trailing_slash(harness: Any, endpoint: str) -> None:
    suggestion_id, before = _setup(harness, endpoint, "slash")
    method, path = _endpoint(endpoint, suggestion_id)
    body = _body(endpoint, suggestion_id)
    response = harness.request(method, path + "/", json=body, follow_redirects=False)
    assert response.status_code in (307, 308), response.text
    _assert_unchanged(harness, suggestion_id, before)
    assert response.headers["location"].rstrip("/").endswith(path)
    response = harness.request(method, path + "/", json=body, follow_redirects=True)
    if endpoint in EDIT_ENDPOINTS:
        assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before)
    elif endpoint == "delete":
        _assert_delete(harness, suggestion_id, response, before)
    else:
        _assert_bulk(harness, [suggestion_id], {suggestion_id: before}, response)


def _run_cors(harness: Any, method: str) -> None:
    suggestion_id, before = _create(harness, "cors")
    response = harness.request("OPTIONS", _endpoint("put", suggestion_id)[1], auth=False, headers={"Origin": "https://example.test", "Access-Control-Request-Method": method, "Access-Control-Request-Headers": f"content-type,{harness.config.api_header}"})
    assert response.status_code == (400 if method == "TRACE" else 200)
    assert response.headers.get("access-control-allow-origin")
    _assert_unchanged(harness, suggestion_id, before)


def _run_authentication(harness: Any, endpoint: str, key: str | None, invalid_body: bool = False) -> None:
    suggestion_id, before = _setup(harness, endpoint, "auth")
    body = {"invalid": True} if invalid_body else _body(endpoint, suggestion_id)
    name, actual = harness.config.api_header, harness.config.api_key
    headers: Any = {}
    if key == "capitalization":
        headers[name.swapcase()] = actual
    elif key == "wrong-header":
        headers[name + "-Wrong"] = actual
    elif key == "pad-key":
        # Use the harness's owned TCP wire path; h11 rejects OWS before sending.
        headers[name] = f" {actual} "
    elif key in ("duplicates", "duplicates-reversed"):
        headers = [(name, "wrong-ascii-key"), (name, actual)]
        if key == "duplicates-reversed":
            headers.reverse()
    elif key == "non-ascii":
        headers = [(name.encode("ascii"), "نامعتبر".encode("utf-8"))]
    elif key is not None:
        headers[name] = key
    try:
        response = _request(harness, endpoint, suggestion_id, body, auth=False, headers=headers, raw_headers=key in ("pad-key", " "))
    except Exception as error:
        if isinstance(error, (ValueError, UnicodeEncodeError)) or type(error).__name__ == "LocalProtocolError":
            raise ScenarioBlocked(f"HTTP client cannot transmit this header: {type(error).__name__}") from error
        raise
    if key == "capitalization":
        if endpoint in EDIT_ENDPOINTS:
            assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before)
        elif endpoint == "delete":
            _assert_delete(harness, suggestion_id, response, before)
        else:
            _assert_bulk(harness, [suggestion_id], {suggestion_id: before}, response)
        return
    # Padded-key and duplicate/non-ASCII probes retain deterministic rejection
    # invariant, even if today's source returns 500 or accepts one value.
    assert_error(response, 401, None if key in ("duplicates", "duplicates-reversed", "non-ascii", "", " ") or invalid_body else "API_KEY_MISSING" if key in (None, "wrong-header") else "API_KEY_INVALID")
    assert response.headers.get("www-authenticate") == "ApiKey"
    assert response.json()["errors"][0]["source"]["pointer"] == f"/headers/{name}"
    _assert_unchanged(harness, suggestion_id, before)


def _run_success_contract(harness: Any, endpoint: str) -> None:
    suggestion_id, before = _setup(harness, endpoint, "contract")
    response = _request(harness, endpoint, suggestion_id, _body(endpoint, suggestion_id))
    if endpoint in EDIT_ENDPOINTS:
        assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before)
    elif endpoint == "delete":
        _assert_delete(harness, suggestion_id, response, before)
    else:
        _assert_bulk(harness, [suggestion_id], {suggestion_id: before}, response)


def _run_request_id(harness: Any, kind: str, supplied: bool | str, endpoint: str | None = None) -> None:
    endpoint = endpoint or {"success": "ingest", "auth": "patch", "validation": "patch", "bulk-partial": "bulk", "lookup": "delete"}[kind]
    if kind == "lookup":
        suggestion_id = harness.new_id("request-id-missing")
        before = harness.snapshot(suggestion_id)
    else:
        suggestion_id, before = _setup(harness, endpoint, "request-id")
    requested = str(uuid.uuid4()) if supplied is True else supplied if isinstance(supplied, str) else None
    headers = {"X-Request-Id": requested} if requested is not None else {}
    if kind == "bulk-partial":
        missing = harness.new_id("missing")
        response = _request(harness, "bulk", suggestion_id, {"suggestionIds": [suggestion_id, missing]}, headers=headers, request_id=False)
        _assert_bulk(harness, [suggestion_id, missing], {suggestion_id: before, missing: harness.snapshot(missing)}, response)
    elif kind == "success":
        response = _request(harness, endpoint, suggestion_id, _body(endpoint, suggestion_id), headers=headers, request_id=False)
        if endpoint in EDIT_ENDPOINTS:
            assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before)
        elif endpoint == "delete":
            _assert_delete(harness, suggestion_id, response, before)
        else:
            _assert_bulk(harness, [suggestion_id], {suggestion_id: before}, response)
    elif kind == "lookup":
        response = _request(harness, endpoint, suggestion_id, None, headers=headers, request_id=False)
        assert_error(response, 404, "SUGGESTION_NOT_FOUND", "/data/suggestionId")
        _assert_unchanged(harness, suggestion_id, before)
    else:
        body = _body(endpoint, suggestion_id)
        if kind == "validation":
            assert body is not None
            body = {**body, "unknown": True}
        response = _request(harness, endpoint, suggestion_id, body, headers=headers, auth=kind != "auth", request_id=False)
        assert_error(response, 422 if kind == "validation" else 401)
        _assert_unchanged(harness, suggestion_id, before)
    returned = response.headers.get("X-Request-Id")
    assert returned, "response missing correlation header"
    uuid.UUID(returned)
    if supplied is True:
        assert returned == requested
    _observe(harness, "request-id", {"endpoint": endpoint, "category": kind, "requested": requested, "returned": returned, "status": response.status_code})


def _run_validation(harness: Any, endpoint: str, field: str | None = None, value: Any = None, omit: bool = False, omit_all: bool = False, wrapper: bool = False, code: str | None = "VALIDATION_ERROR", status: int = 422, expected: dict[str, Any] | None = None, extra: dict[str, Any] | None = None, pointer: str | None = None, preserve_scrutiny: bool = False) -> None:
    suggestion_id, before = _setup(harness, endpoint, "validation")
    body = _body(endpoint, suggestion_id)
    assert body is not None
    if field is not None:
        if omit:
            body.pop(field, None)
        else:
            body[field] = value
    body.update(extra or {})
    if omit_all:
        body = {}
    if wrapper:
        body = {"data": body}
    response = _request(harness, endpoint, suggestion_id, body)
    if status < 300:
        after = assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before, expected=expected)
        if preserve_scrutiny:
            response = _request(harness, "patch", suggestion_id, {"title": "عنوان جدید برای کاهش مصرف انرژی"})
            assert_consistent(harness, suggestion_id, response, previous=after, expected={"committee_scrutiny_id": after["sql"]["committee_scrutiny_id"]})
    else:
        if pointer is None and field is not None and status < 500:
            pointer = "/data/date" if code == "INVALID_SHAMSI_DATE" else "/data/secretariatScrutiny" if field == "tributaryScrutiny" else "/data/secretariatComment" if field == "tributaryComment" else f"/data/{field}"
        assert_error(response, status, code, pointer)
        _assert_unchanged(harness, suggestion_id, before)


def _run_raw_validation(harness: Any, endpoint: str, body: Any, raw: bool = False) -> None:
    suggestion_id, before = _setup(harness, endpoint, "body-shape")
    method, path = _endpoint(endpoint, suggestion_id)
    kwargs = {} if body == "__absent__" else {"content": body, "headers": {"Content-Type": "application/json"}} if raw else {"content": json.dumps(body), "headers": {"Content-Type": "application/json"}}
    response = harness.request(method, path, **kwargs)
    assert_error(response, 422 if not raw or body != b'{"title":"\xff"}' else 400)
    _assert_unchanged(harness, suggestion_id, before)


def _run_optional(harness: Any, endpoint: str, field: str, value: Any) -> None:
    suggestion_id, before = _setup(harness, endpoint, "optional")
    body = _body(endpoint, suggestion_id, full=endpoint == "put")
    assert body is not None
    if value == "__omit__":
        body.pop(field, None)
    else:
        body[field] = value
    response = _request(harness, endpoint, suggestion_id, body)
    sql_name = SQL_FIELDS[field]
    expected = {sql_name: before["sql"][sql_name] if endpoint == "patch" else None}
    if field.endswith("Scrutiny"):
        expected[sql_name + "_id"] = before["sql"][sql_name + "_id"] if endpoint == "patch" else None
    assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before, expected=expected)


def _run_aliases(harness: Any, endpoint: str, side: str, canonical: Any, legacy: Any, snake: bool, status: int) -> None:
    suggestion_id, before = _setup(harness, endpoint, "aliases")
    body = _body(endpoint, suggestion_id)
    assert body is not None
    names = (f"secretariat{side}", f"tributary{side}") if not snake else (f"secretariat_{side.lower()}", f"tributary_{side.lower()}")
    body.update({names[0]: canonical, names[1]: legacy})
    response = _request(harness, endpoint, suggestion_id, body)
    if status == 422:
        assert_error(response, 422, "VALIDATION_ERROR")
        _assert_unchanged(harness, suggestion_id, before)
    else:
        expected = {"secretariat_scrutiny_id": canonical if canonical is not None else legacy} if side == "Scrutiny" else {"secretariat_comment": canonical if canonical is not None else legacy}
        assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before, expected=expected)


def _run_naming(harness: Any, endpoint: str, style: str) -> None:
    suggestion_id, before = _setup(harness, endpoint, "naming")
    body = _body(endpoint, suggestion_id)
    assert body is not None
    body["contextTitle"] = "abcdefghijklmnop"
    if style == "snake":
        for key in ("suggestionId", "contextTitle"):
            if key in body:
                body["suggestion_id" if key == "suggestionId" else "context_title"] = body.pop(key)
    elif style == "mixed":
        body["context_title"] = body.pop("contextTitle")
    else:
        body["context_title"] = "other-context-value"
    response = _request(harness, endpoint, suggestion_id, body)
    if style == "duplicate-alias":
        assert_error(response, 422, "VALIDATION_ERROR")
        _assert_unchanged(harness, suggestion_id, before)
    else:
        assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before, expected={"context_title": "abcdefghijklmnop"})


def _run_media(harness: Any, endpoint: str, media: str | None, accepted: bool) -> None:
    suggestion_id, before = _setup(harness, endpoint, "media")
    method, path = _endpoint(endpoint, suggestion_id)
    response = harness.request(method, path, content=json.dumps(_body(endpoint, suggestion_id)), headers={"Content-Type": media} if media else {})
    if media is None and response.status_code == 422:
        # Frameworks differ on headerless JSON. Characterize rejection with no
        # writes, or require the full success/store oracle when it is decoded.
        assert_error(response, 422, "VALIDATION_ERROR")
        _assert_unchanged(harness, suggestion_id, before)
    elif accepted:
        assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before)
    else:
        assert_error(response, 422, "VALIDATION_ERROR")
        _assert_unchanged(harness, suggestion_id, before)
    _observe(harness, "media-characterization", {"media": media, "status": response.status_code})


def _run_json_characterization(harness: Any, endpoint: str, variant: str) -> None:
    suggestion_id, before = _setup(harness, endpoint, "json-parser")
    body = _body(endpoint, suggestion_id)
    assert body is not None
    if variant.startswith("large"):
        body["problem"] = "energy consumption equipment. " * 400
        if variant == "large-invalid":
            body["unknown"] = "x" * 100000
    if variant == "duplicate-property":
        body["title"] = "first title value"
        content = json.dumps(body, ensure_ascii=False)[:-1] + ',"title":"second title value"}'
    else:
        content = json.dumps(body, ensure_ascii=variant == "escaped-unicode")
    method, path = _endpoint(endpoint, suggestion_id)
    response = harness.request(method, path, content=content.encode("utf-8"), headers={"Content-Type": "application/json"})
    if variant == "large-invalid":
        assert_error(response, 422, "VALIDATION_ERROR")
        _assert_unchanged(harness, suggestion_id, before)
    else:
        assert_consistent(harness, suggestion_id, response, previous=None if endpoint == "ingest" else before, expected={"title": "second title value"} if variant == "duplicate-property" else None)
    _observe(harness, "json-parser", {"variant": variant, "bytes": len(content.encode("utf-8")), "status": response.status_code})


def _run_identity(harness: Any, length: int | None = None, variant: str | None = None) -> None:
    if length is not None:
        unique = harness.new_id("identity")
        if length == 1:
            suggestion_id = next((candidate for candidate in string.ascii_letters + "گچپژ" if harness.snapshot(candidate) == {"sql": None, "points": []}), None)
            if suggestion_id is None:
                raise ScenarioBlocked("No absent one-character ID available without touching seeded sentinels")
        else:
            suggestion_id = (unique + string.ascii_lowercase * 3)[:length]
        harness.register_id(suggestion_id)
        before = harness.snapshot(suggestion_id)
        assert before["sql"] is None and not before["points"], "exact boundary ID is not fresh"
        response = _request(harness, "ingest", suggestion_id, _body("ingest", suggestion_id))
        assert_consistent(harness, suggestion_id, response)
        return
    if variant == "persian":
        suggestion_id = harness.new_id("شناسه-يک")
        _create(harness, "persian", exact_id=suggestion_id)
    elif variant == "trimmed":
        suggestion_id = harness.new_id("trimmed")
        response = _request(harness, "ingest", suggestion_id, {**BASE, "suggestionId": f" {suggestion_id} "})
        assert_consistent(harness, suggestion_id, response)
    else:
        ids = [harness.new_id("Case"), harness.new_id("case")]
        if variant == "case-distinct":
            ids[1] = ids[0].swapcase()
        elif variant == "leading-zero":
            digits = str(int(uuid.uuid4().hex[:10], 16))
            ids = ["00" + digits, digits]
        elif variant == "digit-script":
            digits = str(int(uuid.uuid4().hex[:10], 16))
            ids = [_script_digits(digits, "persian"), _script_digits(digits, "arabic"), digits]
        snapshots = {}
        for suggestion_id in ids:
            _, snapshots[suggestion_id] = _create(harness, "identity", exact_id=suggestion_id)
        for suggestion_id in ids:
            _assert_unchanged(harness, suggestion_id, snapshots[suggestion_id])


def _run_path_identity(harness: Any, variant: str) -> None:
    if variant == "missing-segment":
        response = harness.request("PATCH", "/api/v1/suggestions", json={"title": "valid title"})
        assert_error(response, 404, "RESOURCE_NOT_FOUND")
        return
    suffix = {"space": " path value ", "special": "-#?%+", "slash": "/inner", "long": "x" * 100}[variant]
    suggestion_id = harness.new_id("path") + suffix
    if len(suggestion_id) > 64:
        response = _request(harness, "patch", suggestion_id, {"title": "valid title"})
        assert_error(response, 404, "SUGGESTION_NOT_FOUND")
        return
    # Ingest trims boundary spaces; internal spaces and special characters retain identity.
    suggestion_id = suggestion_id.strip()
    _, before = _create(harness, "path", exact_id=suggestion_id)
    response = _request(harness, "patch", suggestion_id, {"title": "valid title"})
    if variant == "slash":
        assert_error(response, 404, "RESOURCE_NOT_FOUND")
        _assert_unchanged(harness, suggestion_id, before)
    else:
        assert_consistent(harness, suggestion_id, response, previous=before, expected={"title": "valid title"})


def _run_exact_path_whitespace(harness: Any, endpoint: str, side: str) -> None:
    suggestion_id, before = _create(harness, "exact-path")
    path_id = (" " if side in ("leading", "surrounding") else "") + suggestion_id + (" " if side in ("trailing", "surrounding") else "")
    harness.register_id(path_id)
    absent = harness.snapshot(path_id)
    assert absent == {"sql": None, "points": []}
    response = _request(harness, endpoint, path_id, _body(endpoint, path_id))
    assert_error(response, 404, "SUGGESTION_NOT_FOUND", "/data/suggestionId")
    _assert_unchanged(harness, suggestion_id, before)
    _assert_unchanged(harness, path_id, absent)


def _run_route_word(harness: Any, word: str, endpoint: str) -> None:
    suggestion_id, before = _create(harness, "route-word", exact_id=word)
    response = _request(harness, endpoint, suggestion_id, _body(endpoint, suggestion_id))
    if endpoint == "delete":
        _assert_delete(harness, suggestion_id, response, before)
    else:
        assert_consistent(harness, suggestion_id, response, previous=before)


def _run_delete_incidental(harness: Any) -> None:
    suggestion_id, before = _create(harness, "incidental")
    other_id, sentinel = _create(harness, "incidental-other")
    response = harness.request("DELETE", _endpoint("delete", suggestion_id)[1] + f"?suggestionId={quote(other_id)}&unknown=true", json={"suggestionId": other_id})
    _assert_delete(harness, suggestion_id, response, before)
    _assert_unchanged(harness, other_id, sentinel)


def _long_field(kind: str, count: int = 50, separator: str = "paragraph") -> str:
    if separator == "word-boundaries":
        return " ".join(f"{kind}{index:04d}" for index in range(count * 10))
    sep = {"paragraph": ".\n\n", "newline": "\n", "persian-punctuation": "؛"}[separator]
    return sep.join(f"{kind} segment {index:04d} energy equipment efficiency control monitoring " + ("abcdefghijklmno " * 7) for index in range(count))


def _assert_chunk_coverage_and_overlap(harness: Any, snapshot: dict[str, Any], field_name: str, *, require_overlap: bool = False) -> None:
    """Locate persisted chunks in unique fixture text, independently of splitting."""
    source = snapshot["sql"][field_name].strip()
    chunks = sorted((point["payload"] for point in snapshot["points"] if point["payload"]["chunk_type"] == field_name), key=lambda payload: payload["sub_index"])
    assert len(chunks) > 1
    previous_start, previous_end = -1, 0
    observed_overlaps = []
    for chunk in chunks:
        content = chunk["content"]
        assert len(content) <= getattr(harness.config, "max_chunk_chars", 1500)
        start = source.find(content, previous_start + 1)
        assert start >= 0, f"{field_name} chunk is not an ordered contiguous source slice"
        if previous_start == -1:
            assert start == 0, f"{field_name} leading source text omitted"
        elif start >= previous_end:
            assert not source[previous_end:start].strip(), f"{field_name} text lost between chunks"
        overlap = max(0, previous_end - start)
        assert overlap <= getattr(harness.config, "overlap_chars", 150), f"{field_name} overlap exceeds configured bound: {overlap}"
        if previous_start >= 0:
            observed_overlaps.append(overlap)
            if require_overlap:
                assert overlap > 0, f"{field_name} word-boundary chunks have no overlap"
        previous_start, previous_end = start, start + len(content)
    assert previous_end == len(source), f"{field_name} trailing source text omitted"
    _observe(harness, "chunk-overlap", {"field": field_name, "overlaps": observed_overlaps, "required": require_overlap})


def _normalized_threshold_fixture(normalization: str) -> tuple[str, str]:
    # Fourteen plain letters plus one removable code point: raw 15, normalized 14.
    golden = "abcdefghijklmn"
    raw = "abcdefg\u064ehijklmn" if normalization == "diacritic" else "abcdefghijklmn😀"
    assert len(raw) == 15 and len(golden) == 14
    return raw, golden


def _run_ingestion(harness: Any, variant: str, **params: Any) -> None:
    suggestion_id = harness.new_id("ingestion")
    fields = dict(BASE)
    expected: dict[str, Any] = {}
    count: int | None = 3
    protected: list[str] = []
    if variant == "full":
        fields.update(FULL)
        count = 4
        expected = {"shamsi_date": "1403/02/18", "committee_scrutiny_id": 0, "secretariat_scrutiny_id": -2}
    elif variant in ("committee-only", "secretariat-only", "both", "one-substantive"):
        if variant in ("committee-only", "both") or variant == "one-substantive" and params["side"] == "committee":
            fields["description"] = "abcdefghijklmnop"
        if variant in ("secretariat-only", "both") or variant == "one-substantive" and params["side"] == "secretariat":
            fields["secretariatComment"] = "qrstuvwxyzabcdef"
        if variant == "one-substantive":
            other = "secretariatComment" if params["side"] == "committee" else "description"
            fields[other] = "abcd" if params["other"] == "short" else "ندارد"
            fields.update({"committeeScrutiny": -3, "secretariatScrutiny": -2})
        count = 4
    elif variant == "scrutiny-only":
        fields.update({"committeeScrutiny": 0, "secretariatScrutiny": -2})
    elif variant in ("comment-length", "comment-noise"):
        field_name = params["field"]
        fields[field_name] = string.ascii_lowercase[:params["length"]] if variant == "comment-length" else params["value"]
        count = 4 if variant == "comment-length" and params["length"] >= 15 else 3
    elif variant == "normalized-comment-threshold":
        raw, golden = _normalized_threshold_fixture(params["normalization"])
        fields[params["field"]] = raw
        expected[SQL_FIELDS[params["field"]]] = golden
    elif variant == "context":
        fields["contextTitle"] = params["context"]
        expected["context_title"] = params["context"]
    elif variant == "long":
        fields["problem"] = _long_field("problem", separator=params["separator"])
        fields["solution"] = _long_field("solution", separator=params["separator"])
        count = None
    elif variant in ("long-title", "long-evaluation", "unbroken-problem", "unbroken-solution"):
        name = {"long-title": "title", "long-evaluation": "description", "unbroken-problem": "problem", "unbroken-solution": "solution"}[variant]
        fields[name] = (string.ascii_lowercase * 80) if variant.startswith("unbroken") else _long_field("title" if name == "title" else "comment", 20)
        count = 4 if name == "description" else 3
    elif variant == "unicode":
        data = {
            "arabic-letters": ("كتاب يارانه", "کتاب یارانه"),
            "diacritics": ("مَصرَف اِنرژی", "مصرف انرژی"),
            "emoji": ("مصرف انرژی 😀", "مصرف انرژی"),
            "repeated": ("مصرففف انرژی", "مصرفف انرژی"),
            "zwnj": ("صرفه\u200cجویی انرژی", "صرفه\u200cجویی انرژی"),
            "digits": ("مصرف انرژی ۱۲۳ ٤٥٦", "مصرف انرژی 123 456"),
            "whitespace": ("  مصرف\tانرژی\nتجهیزات  ", "مصرف انرژی\nتجهیزات"),
        }
        value, golden = data[params["unicode_variant"]]
        fields["problem"] = value
        if golden is not None:
            expected["problem"] = golden
    elif variant == "markdown":
        data = {
            "heading": ("### مصرف انرژی", ["### "]),
            "list": ("- مصرف انرژی\n- کنترل تجهیزات", ["- "]),
            "checklist": ("- [ ] مصرف انرژی\n- [x] کنترل تجهیزات", ["- [ ] ", "- [x] "]),
            "code": ("مصرف انرژی `x = ۱ + 2`\n```python\nx = 'يک'\n```", ["`x = ۱ + 2`", "```python\nx = 'يک'\n```"]),
            "table": ("| مصرف | انرژی |\n| :---: | --- |\n| 1 | 2 |", ["| :---: | --- |"]),
            "url": ("مصرف انرژی https://example.test/a?q=۱&x=ي", ["https://example.test/a?q=۱&x=ي"]),
            "link": ("مصرف انرژی [كتاب](https://example.test/ي?q=۱)", ["](https://example.test/ي?q=۱)"]),
            "math": ("مصرف انرژی $x_۱ + y = 2$", ["$x_۱ + y = 2$"]),
            "decimal": ("مصرف انرژی 0.5 تجهیزات", ["0.5"]),
        }
        fields["problem"], protected = data[params["markdown_variant"]]
    elif variant == "stopwords":
        fields.update({"title": "از به در با", "problem": "از به در با", "solution": "از به در با"})
    elif variant.startswith("bm25-max"):
        limit = getattr(harness.config, "bm25_max_token_length", 40)
        delta = -1 if variant.endswith("minus-one") else 1 if variant.endswith("plus-one") else 0
        fields["problem"] = (string.ascii_lowercase * 5)[:limit + delta] + " مصرف انرژی"
    elif variant == "batch-boundary":
        size = getattr(harness.config, "qdrant_batch_size", 64) if params["boundary"] == "qdrant" else getattr(harness.config, "embedding_batch_size", 128)
        target = size + params["delta"]
        # Exactly N chunks: title + solution + N-2 problem pieces.  Each
        # paragraph is 1400 characters, which cannot share a 1500-char chunk.
        paragraphs = []
        for index in range(target - 2):
            seed = f"problem{index:04d} " + string.ascii_lowercase + " "
            paragraphs.append((seed * (1400 // len(seed) + 1))[:1400])
        fields["problem"] = "\n\n".join(paragraphs)
        count = target
    elif variant == "independent-enums":
        fields.update({"status": "APPROVED", "committeeScrutiny": "REJECTED", "secretariatScrutiny": "DUPLICATE"})
        expected = {"status_id": 3, "committee_scrutiny_id": 1, "secretariat_scrutiny_id": 6}
    elif variant == "placeholder":
        fields["problem"] = "مصرف انرژی _TAVANIR_TOKEN_0_ و `x = ۱`"
        protected = ["_TAVANIR_TOKEN_0_", "`x = ۱`"]
    response = _request(harness, "ingest", suggestion_id, {**fields, "suggestionId": suggestion_id})
    if variant in ("long-title", "long-evaluation", "unbroken-problem", "unbroken-solution") and response.status_code >= 400:
        assert_error(response, 500, "EMBEDDING_FAILED")
        assert harness.snapshot(suggestion_id) == {"sql": None, "points": []}
        _observe(harness, "provider-context-limit", {"variant": variant, "status": response.status_code})
        return
    expected = {**{key: value for key, value in BASE_GOLDEN.items() if fields[key] == BASE[key]}, **expected}
    after = assert_consistent(harness, suggestion_id, response, expected=expected, count=count)
    for token in protected:
        assert token in after["sql"]["problem"], f"protected/literal text corrupted: {token}"
        assert any(token in point["payload"]["content"] for point in after["points"] if point["payload"]["chunk_type"] == "problem")
    if variant == "long":
        for name in ("problem", "solution"):
            word_boundaries = params["separator"] == "word-boundaries"
            _assert_chunk_coverage_and_overlap(harness, after, name, require_overlap=word_boundaries)
            chunks = [point["payload"] for point in after["points"] if point["payload"]["chunk_type"] == name]
            for number in range(500 if word_boundaries else 50):
                marker = f"{name}{number:04d}" if word_boundaries else f"{name} segment {number:04d}"
                assert any(marker in chunk["content"] for chunk in chunks), "chunk omission"
    if variant == "stopwords":
        lengths = [len(point.get("vector", point.get("vectors"))[harness.config.sparse_name]["indices"]) for point in after["points"]]
        assert lengths == [0] * len(after["points"]), "the independent all-stopword fixture unexpectedly retained lexical terms"
        _observe(harness, "stopword-sparse-lengths", lengths)
    elif variant.startswith("bm25-max"):
        import mmh3

        limit = getattr(harness.config, "bm25_max_token_length", 40)
        delta = -1 if variant.endswith("minus-one") else 1 if variant.endswith("plus-one") else 0
        token = (string.ascii_lowercase * 5)[:limit + delta]
        index = mmh3.hash(token, signed=False)
        sparse_indices = next(point.get("vector", point.get("vectors"))[harness.config.sparse_name]["indices"] for point in after["points"] if point["payload"]["chunk_type"] == "problem")
        assert (index in sparse_indices) == (delta <= 0), "BM25 token-length filtering boundary is inconsistent"


def _run_duplicate(harness: Any, variant: str) -> None:
    suggestion_id, before = _create(harness, "duplicate", full=False)
    if variant == "deleted":
        before = _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), before)
    body = {**BASE, "suggestionId": suggestion_id}
    if variant == "different-active":
        body["title"] = "completely different title"
    elif variant == "domain-invalid":
        body["title"] = "abcd"
    elif variant == "schema-invalid":
        body["title"] = None
    response = _request(harness, "ingest", suggestion_id, body)
    assert_error(response, 422 if variant == "schema-invalid" else 409, "VALIDATION_ERROR" if variant == "schema-invalid" else "SUGGESTION_ALREADY_EXISTS", None if variant == "schema-invalid" else "/data/suggestionId")
    _assert_unchanged(harness, suggestion_id, before)


def _run_residual_ingestion(harness: Any, state: str | None = None, variant: str | None = None) -> None:
    suggestion_id, before = _create(harness, "residual")
    if variant == "sql-without-points":
        harness.clear_parent_points(suggestion_id)
        before = harness.snapshot(suggestion_id)
        response = _request(harness, "ingest", suggestion_id, _body("ingest", suggestion_id))
        assert_error(response, 409, "SUGGESTION_ALREADY_EXISTS")
        _assert_unchanged(harness, suggestion_id, before)
        return
    # Exact administrative row removal preserves the cloned residual points.
    if not hasattr(harness, "remove_sql_row"):
        raise ScenarioBlocked("Residual-vector setup requires owned remove_sql_row(id)")
    harness.append_cloned_points(suggestion_id, ("active", "staging", "deprecated") if state == "mixed" else (state or "active",))
    harness.remove_sql_row(suggestion_id)
    before = harness.snapshot(suggestion_id)
    assert before["sql"] is None and before["points"]
    body = _body("ingest", suggestion_id)
    if variant == "orphan-validation-failure":
        assert body is not None
        body["title"] = None
    response = _request(harness, "ingest", suggestion_id, body)
    if variant == "orphan-validation-failure":
        assert_error(response, 422, "VALIDATION_ERROR")
        _assert_unchanged(harness, suggestion_id, before)
    else:
        after = assert_consistent(harness, suggestion_id, response)
        assert {str(point["id"]) for point in before["points"]}.isdisjoint(str(point["id"]) for point in after["points"])


def _run_put(harness: Any, variant: str, **params: Any) -> None:
    if variant == "missing":
        suggestion_id = harness.new_id("missing-put")
        before = harness.snapshot(suggestion_id)
        assert_error(_request(harness, "put", suggestion_id, dict(BASE)), 404, "SUGGESTION_NOT_FOUND", "/data/suggestionId")
        _assert_unchanged(harness, suggestion_id, before)
        return
    fields = {"problem": _long_field("problem"), "solution": _long_field("solution")} if variant == "shrink" else None
    suggestion_id, before = _create(harness, "put", fields=fields)
    if variant.startswith("deleted"):
        before = _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), before)
        if variant == "deleted-residual":
            # Store helper retains a template snapshot from before deletion.
            harness.append_cloned_points(suggestion_id, ("active", "staging", "deprecated"))
            before = harness.snapshot(suggestion_id)
    body = dict(FULL if variant in ("full", "metadata", "grow", "identical-twice") else BASE)
    expected: dict[str, Any] = {}
    count: int | None = 4 if body is not BASE and "description" in body else 3
    if variant in ("omitted", "null", "blank"):
        if variant != "omitted":
            body.update({key: None if variant == "null" else " " for key in OPTIONAL_FIELDS})
        expected = {value: None for value in SQL_FIELDS.values()}
        expected.update({"committee_scrutiny_id": None, "secretariat_scrutiny_id": None})
    elif variant == "full":
        body.update({"title": "updated full title", "problem": "updated full problem", "solution": "updated full solution", "status": "EXECUTED", "committeeScrutiny": -3, "secretariatScrutiny": 15, "shamsiDate": "1404/03/19", "contextTitle": "updated context title", "description": "updated committee commentary", "secretariatComment": "updated secretariat commentary"})
        expected = {"title": "updated full title", "problem": "updated full problem", "solution": "updated full solution", "status_id": 5, "committee_scrutiny_id": -3, "secretariat_scrutiny_id": 15, "shamsi_date": "1404/03/19", "context_title": "updated context title", "description": "updated committee commentary", "secretariat_comment": "updated secretariat commentary"}
    elif variant == "body-id":
        value = params["value"]
        if value != "__omit__":
            body["suggestionId"] = suggestion_id if value == "__match__" else f" {suggestion_id} " if value == "__padded__" else harness.new_id("other") if value == "__different__" else value
        if value == "__different__":
            assert_error(_request(harness, "put", suggestion_id, body), 422, "VALIDATION_ERROR")
            _assert_unchanged(harness, suggestion_id, before)
            return
    elif variant == "metadata":
        name = params["field"]
        value = {"status": "EXECUTED", "committeeScrutiny": -3, "secretariatScrutiny": 15, "shamsiDate": "1404/03/19", "contextTitle": "updated context title"}[name]
        body[name] = value
        expected = {"status_id": 5} if name == "status" else {SQL_FIELDS[name] + "_id": value} if name.endswith("Scrutiny") else {SQL_FIELDS[name]: value}
    elif variant == "grow":
        body.update({"problem": _long_field("problem", separator="word-boundaries"), "solution": _long_field("solution", separator="word-boundaries")})
        expected = {name: body[name] for name in ("problem", "solution")}
        count = None
    elif variant in ("modern", "legacy"):
        cleared = assert_consistent(harness, suggestion_id, _request(harness, "put", suggestion_id, dict(BASE)), previous=before, count=3)
        before = cleared
        body["secretariatScrutiny" if variant == "modern" else "tributaryScrutiny"] = -2
        body["secretariatComment" if variant == "modern" else "tributaryComment"] = "restored secretariat commentary"
        expected = {"secretariat_scrutiny_id": -2, "secretariat_comment": "restored secretariat commentary"}
        count = 4
    response = _request(harness, "put", suggestion_id, body)
    after = assert_consistent(harness, suggestion_id, response, previous=before, expected=expected, count=count)
    if variant == "grow":
        assert len(after["points"]) > len(before["points"]), "long replacement did not increase the chunk count"
        for name in ("problem", "solution"):
            _assert_chunk_coverage_and_overlap(harness, after, name, require_overlap=True)
    elif variant == "identical-twice":
        assert_consistent(harness, suggestion_id, _request(harness, "put", suggestion_id, body), previous=after, expected={key: value for key, value in after["sql"].items() if key not in ("version", "updated_at", "created_at")}, count=count)


def _run_patch(harness: Any, variant: str, **params: Any) -> None:
    if variant == "missing":
        suggestion_id = harness.new_id("missing-patch")
        before = harness.snapshot(suggestion_id)
        assert_error(_request(harness, "patch", suggestion_id, {"title": "valid new title"}), 404, "SUGGESTION_NOT_FOUND")
        _assert_unchanged(harness, suggestion_id, before)
        return
    creation_fields = {"problem": _long_field("problem"), "solution": _long_field("solution")} if variant == "shrink" else None
    suggestion_id, before = _create(harness, "patch", full=variant not in ("comment-only", "scrutiny-only", "preserve-independent"), fields=creation_fields)
    body: dict[str, Any] = {"title": "valid new title"}
    expected: dict[str, Any] = {}
    code: str | None = None
    if variant == "deleted":
        before = _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), before)
        code = "SUGGESTION_NOT_FOUND"
    elif variant == "single-field":
        name = params["field"]
        value = {"title": "new title value", "problem": "new problem value", "solution": "new solution value", "status": "EXECUTED", "committeeScrutiny": -3, "description": "new committee description", "shamsiDate": "1404/03/19", "contextTitle": "new context value", "secretariatScrutiny": 15, "secretariatComment": "new secretariat commentary"}[name]
        body = {name: value}
        expected = {"status_id": 5} if name == "status" else {SQL_FIELDS[name] + "_id": value} if name.endswith("Scrutiny") else {SQL_FIELDS.get(name, name): value}
    elif variant == "ignored-null":
        name = params["field"]
        body = {"solution" if name == "title" else "title": "valid new value", name: None}
        sql_name = "status_id" if name == "status" else SQL_FIELDS.get(name, name)
        expected[sql_name] = before["sql"][sql_name]
    elif variant in ("empty", "all-null"):
        body = {} if variant == "empty" else {name: None for name in (*CORE_FIELDS, "status", *OPTIONAL_FIELDS)}
        code = "VALIDATION_ERROR"
    elif variant == "forbidden-id":
        value = params["value"]
        body[params["field"]] = suggestion_id if value == "matching" else "different" if value == "different" else value
        code = "VALIDATION_ERROR"
    elif variant == "invalid-core":
        body = {params["field"]: params["value"]}
        code = "VALIDATION_ERROR" if not params["value"].strip() else "INVALID_SUGGESTION_CONTENT"
    elif variant in ("blank-noop", "blank-overlay"):
        name = params["field"]
        body = {name: params["value"]}
        if variant == "blank-overlay":
            body["title"] = "valid new title"
            expected[SQL_FIELDS[name]] = before["sql"][SQL_FIELDS[name]]
        else:
            code = "VALIDATION_ERROR"
    elif variant in ("comment-only", "scrutiny-only", "preserve-independent"):
        body = {"secretariatComment": "new secretariat commentary"} if variant != "scrutiny-only" else {"secretariatScrutiny": -2}
        expected = {"secretariat_comment": "new secretariat commentary"} if variant != "scrutiny-only" else {"secretariat_scrutiny_id": -2, "secretariat_comment": None}
    elif variant == "threshold":
        body = {params["field"]: string.ascii_lowercase[:params["length"]], "description" if params["field"] == "secretariatComment" else "secretariatComment": "abcd"}
    elif variant == "normalized-comment-threshold":
        raw, golden = _normalized_threshold_fixture(params["normalization"])
        body = {params["field"]: raw, "description" if params["field"] == "secretariatComment" else "secretariatComment": "abcd"}
        expected[SQL_FIELDS[params["field"]]] = golden
    elif variant == "shrink":
        body = {"problem": "new short problem", "solution": "new short solution"}
    elif variant == "multiple":
        body = {"title": "new coherent title", "status": "EXECUTED", "contextTitle": "new coherent context", "description": "new coherent description", "secretariatScrutiny": 15}
        expected = {"title": "new coherent title", "status_id": 5, "context_title": "new coherent context", "description": "new coherent description", "secretariat_scrutiny_id": 15}
    elif variant == "identical-twice":
        body = {"title": before["sql"]["title"]}
    elif variant in ("modern", "legacy"):
        body = {"secretariatScrutiny" if variant == "modern" else "tributaryScrutiny": 15, "secretariatComment" if variant == "modern" else "tributaryComment": "new secretariat commentary"}
        expected = {"secretariat_scrutiny_id": 15, "secretariat_comment": "new secretariat commentary"}
    elif variant == "committee-ambiguity":
        body = {"committeeScrutiny": "تایید"}
        expected = {"committee_scrutiny_id": 0}
    elif variant == "conflict":
        body = {"secretariatScrutiny": -2, "tributaryScrutiny": 15}
        code = "VALIDATION_ERROR"
    elif variant == "atomic-validation":
        body = {"title": "valid new title", "contextTitle": "valid new context", "status": 99}
        code = "INVALID_SUGGESTION_STATUS"
    response = _request(harness, "patch", suggestion_id, body)
    if code:
        assert_error(response, 404 if code == "SUGGESTION_NOT_FOUND" else 422, code)
        _assert_unchanged(harness, suggestion_id, before)
        return
    after = assert_consistent(harness, suggestion_id, response, previous=before, expected=expected)
    unchanged = {"title", "problem", "solution", "status_id", *SQL_FIELDS.values(), "committee_scrutiny_id", "secretariat_scrutiny_id"}
    changed = {"status_id" if key == "status" else SQL_FIELDS.get(key, key) for key, value in body.items() if value is not None and (not isinstance(value, str) or value.strip())}
    if any(key.endswith("Scrutiny") for key in body):
        changed.update(SQL_FIELDS[key] + "_id" for key in body if key.endswith("Scrutiny"))
    for key in unchanged - changed:
        assert after["sql"][key] == before["sql"][key], f"unrelated overlay changed {key}"
    if variant == "threshold":
        assert len(after["points"]) == (4 if params["length"] >= 15 else 3)
    elif variant == "normalized-comment-threshold":
        assert len(after["points"]) == 3, "evaluation eligibility used raw rather than normalized commentary length"
    elif variant == "shrink":
        assert len(after["points"]) == 4
    elif variant == "identical-twice":
        assert_consistent(harness, suggestion_id, _request(harness, "patch", suggestion_id, body), previous=after, expected={"title": before["sql"]["title"]})
    elif variant == "preserve-independent":
        second = assert_consistent(harness, suggestion_id, _request(harness, "patch", suggestion_id, {"secretariatScrutiny": -2}), previous=after, expected={"secretariat_comment": "new secretariat commentary", "secretariat_scrutiny_id": -2})
        assert_consistent(harness, suggestion_id, _request(harness, "patch", suggestion_id, {"title": "third independent title"}), previous=second, expected={"secretariat_comment": "new secretariat commentary", "secretariat_scrutiny_id": -2})


def _run_delete(harness: Any, variant: str) -> None:
    if variant.startswith("missing"):
        if variant == "missing-orphans":
            suggestion_id, before = _create(harness, "delete-orphan")
            if not hasattr(harness, "remove_sql_row"):
                raise ScenarioBlocked("Missing-row/orphan setup requires remove_sql_row(id)")
            harness.remove_sql_row(suggestion_id)
        else:
            suggestion_id = harness.new_id("missing-delete")
        before = harness.snapshot(suggestion_id)
        assert_error(_request(harness, "delete", suggestion_id, None), 404, "SUGGESTION_NOT_FOUND", "/data/suggestionId")
        _assert_unchanged(harness, suggestion_id, before)
        return
    suggestion_id, before = _create(harness, "delete", fields={"problem": _long_field("problem"), "solution": _long_field("solution")} if variant == "many" else None)
    if variant == "zero-points":
        harness.clear_parent_points(suggestion_id)
        before = harness.snapshot(suggestion_id)
    elif variant == "mixed":
        harness.append_cloned_points(suggestion_id, ("staging", "deprecated"))
        before = harness.snapshot(suggestion_id)
    elif variant == "deleted-orphans":
        deleted = _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), before)
        harness.append_cloned_points(suggestion_id, ("active", "staging", "deprecated"))
        before = harness.snapshot(suggestion_id)
        assert deleted["sql"] == before["sql"] and before["points"]
    after = _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), before)
    if variant == "repeat":
        _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), after)
    elif variant == "restore-put":
        assert_consistent(harness, suggestion_id, _request(harness, "put", suggestion_id, dict(BASE)), previous=after, count=3)
    elif variant in ("reject-patch", "reject-ingest"):
        endpoint = "patch" if variant == "reject-patch" else "ingest"
        assert_error(_request(harness, endpoint, suggestion_id, _body(endpoint, suggestion_id)), 404 if endpoint == "patch" else 409, "SUGGESTION_NOT_FOUND" if endpoint == "patch" else "SUGGESTION_ALREADY_EXISTS")
        _assert_unchanged(harness, suggestion_id, after)


def _assert_bulk(harness: Any, ids: list[str], before: dict[str, dict[str, Any]], response: Any) -> None:
    missing = [index for index, suggestion_id in enumerate(ids) if before[suggestion_id]["sql"] is None]
    expected_status = 400 if len(missing) == len(ids) else 207 if missing else 200
    assert response.status_code == expected_status, response.text
    body = response.json()
    success = [suggestion_id for suggestion_id in ids if before[suggestion_id]["sql"] is not None]
    if success:
        assert body["status"] == expected_status
        assert body["data"] == [{"suggestionId": suggestion_id, "status": "DELETED"} for suggestion_id in success]
    else:
        assert "data" not in body and "status" not in body
    errors = body.get("errors", [])
    assert len(errors) == len(missing)
    for error, index in zip(errors, missing, strict=True):
        assert error["status"] == 404 and error["code"] == "SUGGESTION_NOT_FOUND"
        assert error["source"]["pointer"] == f"/data/suggestionIds/{index}"
    for suggestion_id in ids:
        if before[suggestion_id]["sql"] is None:
            _assert_unchanged(harness, suggestion_id, before[suggestion_id])
        else:
            after = harness.snapshot(suggestion_id)
            row_before, row_after = before[suggestion_id]["sql"], after["sql"]
            assert after["sql"]["is_deleted"] is True
            assert after["sql"]["version"] == before[suggestion_id]["sql"]["version"] + int(not before[suggestion_id]["sql"]["is_deleted"])
            assert after["points"] == [], f"bulk reported success but vectors remain: {suggestion_id}"
            if before[suggestion_id]["sql"]["is_deleted"]:
                assert after["sql"] == before[suggestion_id]["sql"]
            else:
                for name, value in row_before.items():
                    if name not in ("version", "is_deleted", "updated_at"):
                        assert row_after[name] == value, f"bulk deletion changed retained field {name}: {suggestion_id}"
                assert row_after["created_at"] == row_before["created_at"]
                assert row_after["updated_at"], "bulk deletion lost its update timestamp"
                _observe(harness, "bulk-timestamps", {"id": suggestion_id, "created_at": row_after["created_at"], "before_updated_at": row_before["updated_at"], "after_updated_at": row_after["updated_at"]})


def _run_bulk(harness: Any, variant: str, position: int | None = None) -> None:
    count = 100 if variant in ("hundred", "hundred-latency") else 1 if variant == "one" else 3
    ids: list[str] = []
    before: dict[str, dict[str, Any]] = {}
    for index in range(count):
        if variant == "all-missing" or variant in ("partial", "trimmed-partial", "repeat-partial") and index == (position if position is not None else 1):
            suggestion_id = harness.new_id("bulk-missing")
            snapshot = harness.snapshot(suggestion_id)
        else:
            exact = ids[0].swapcase() if variant == "case-distinct" and index == 1 else None
            suggestion_id, snapshot = _create(harness, "bulk", full=index == 0, exact_id=exact)
        ids.append(suggestion_id)
        before[suggestion_id] = snapshot
        if variant == "all-deleted" or variant == "active-and-deleted" and index == 1 or variant == "deleted-orphans" and index == 1:
            before[suggestion_id] = _assert_delete(harness, suggestion_id, _request(harness, "delete", suggestion_id, None), snapshot)
            if variant == "deleted-orphans":
                harness.append_cloned_points(suggestion_id, ("active", "staging", "deprecated"))
                before[suggestion_id] = harness.snapshot(suggestion_id)
    input_ids = [f" {suggestion_id} " for suggestion_id in ids] if variant in ("trimmed", "trimmed-partial") else ids
    start = time.monotonic()
    response = _request(harness, "bulk", ids[0], {"suggestionIds": input_ids})
    latency = time.monotonic() - start
    _assert_bulk(harness, ids, before, response)
    if variant.startswith("repeat-"):
        repeated_before = {suggestion_id: harness.snapshot(suggestion_id) for suggestion_id in ids}
        _assert_bulk(harness, ids, repeated_before, _request(harness, "bulk", ids[0], {"suggestionIds": ids}))
    if variant == "hundred-latency":
        _observe(harness, "bulk-100-latency", {"seconds": latency, "items": 100, "sla": None})
        fresh, initial = _create(harness, "post-bulk-pool")
        assert_consistent(harness, fresh, _request(harness, "patch", fresh, {"title": "pool recovery verification"}), previous=initial)


def _run_bulk_invalid(harness: Any, body: dict[str, Any] | None = None, duplicate: str | None = None, code: str = "VALIDATION_ERROR") -> None:
    suggestion_id, before = _create(harness, "bulk-invalid")
    if duplicate:
        body = {"suggestionIds": [suggestion_id, f" {suggestion_id} " if duplicate == "duplicate-trimmed" else suggestion_id]}
    else:
        # Copy through JSON to keep immutable descriptor data unchanged.
        body = json.loads(json.dumps(body))
        if isinstance(body.get("suggestionIds"), list):
            body["suggestionIds"] = [suggestion_id if value == "__existing__" else value for value in body["suggestionIds"]]
    result = assert_error(_request(harness, "bulk", suggestion_id, body), 422, code)
    for error in result["errors"]:
        pointer = (error.get("source") or {}).get("pointer", "")
        assert pointer.startswith("/data/suggestionIds") or pointer == "/data/unknown", error
    _assert_unchanged(harness, suggestion_id, before)


def _run_restart(harness: Any) -> None:
    suggestion_id, before = _create(harness, "restart")
    harness.restart()
    _assert_unchanged(harness, suggestion_id, before)
    _run_host(harness, "/health")
    assert_consistent(harness, suggestion_id, _request(harness, "patch", suggestion_id, {"title": "valid title after restart"}), previous=before)


def _run_flow(harness: Any, variant: str) -> None:
    if variant == "persistent-restart":
        _run_restart(harness)
        return
    suggestion_id, snapshot = _create(harness, "lifecycle")
    if variant in ("put", "patch", "delete", "bulk"):
        other_id, other = _create(harness, "unrelated-sentinel", fields={"title": "distinguishable untouched sentinel"})
        response = _request(harness, variant, suggestion_id, _body(variant, suggestion_id))
        if variant in EDIT_ENDPOINTS:
            assert_consistent(harness, suggestion_id, response, previous=snapshot)
        elif variant == "delete":
            _assert_delete(harness, suggestion_id, response, snapshot)
        else:
            _assert_bulk(harness, [suggestion_id], {suggestion_id: snapshot}, response)
        _assert_unchanged(harness, other_id, other)
        return
    sequence = (("patch", {"title": "first lifecycle title"}), ("put", dict(BASE)), ("delete", None), ("delete", None), ("put", dict(BASE)))
    versions = [snapshot["sql"]["version"]]
    for endpoint, body in sequence:
        if variant == "validation-and-auth-each-stage":
            assert_error(_request(harness, endpoint, suggestion_id, body, auth=False), 401, "API_KEY_MISSING")
            _assert_unchanged(harness, suggestion_id, snapshot)
            if endpoint != "delete":
                assert_error(_request(harness, endpoint, suggestion_id, {"unknown": True}), 422)
                _assert_unchanged(harness, suggestion_id, snapshot)
        response = _request(harness, endpoint, suggestion_id, body)
        snapshot = _assert_delete(harness, suggestion_id, response, snapshot) if endpoint == "delete" else assert_consistent(harness, suggestion_id, response, previous=snapshot)
        versions.append(snapshot["sql"]["version"])
    assert versions == [1, 2, 3, 4, 4, 5]


__all__ = ["Scenario", "ScenarioBlocked", "NORMAL_SCENARIOS", "execute_scenario", "assert_consistent", "assert_error"]
