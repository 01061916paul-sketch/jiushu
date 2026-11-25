#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_daily_api.py - tender-pipeline API 主引擎 (pcc-api.openfun.app)
嚴格精準版：
1. 僅蒐集「勞務類」且為今日新公告／有效招標公告（排除決標公告、無法決標、公開閱覽、已截止案件）
2. 完整備份當日勞務類至 archive/YYYY-MM-DD_classified.json（供查驗使用）
3. 針對 A 類調閱明細：
   - 取最新一筆招標紀錄（reversed），絕不取到舊公告
   - 領標金取「領投開標:是否提供電子領標:總計」（含機關文件費＋系統使用費＋文件代收費）
   - 驗證「截止投標」尚未過期；已過期者不列入今日有效標案
   - 凡「是否須繳納履約保證金」為「是」者，一律移入 C 類（使用者規則：須繳履約保證金）
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from classify_stage1 import classify_tender  # noqa: E402

BASE_URL = "https://pcc-api.openfun.app/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JiushuTenderPipeline/2.1)"}

EXCLUDED_TYPES = ("決標", "無法決標", "公開閱覽", "公開徵求廠商提供參考資料")
CENTRAL_KW = ("臺中", "台中", "彰化", "南投", "苗栗", "雲林")
PURE_PLANNING_KW = ("規劃", "企劃", "策展", "顧問", "研究", "先期", "策略", "地方創生")
HIGH_PROB_A_KW = PURE_PLANNING_KW + ("活動辦理", "活動執行", "行銷", "推廣", "論壇", "工作坊", "展覽", "節慶", "藝術", "文化")
STRICT_C_NAME_KW = ("手冊", "指引", "調查評估", "維護", "維運", "塢修", "檢驗", "SROI", "永續績效", "系統測試", "教育推廣")
STRICT_C_CAT_CODES = ("886", "812", "71", "73", "94")


def score_priority(item: dict, is_b: bool = False) -> tuple:
    text = f"{item.get('org', '')} {item.get('address', '')} {item.get('name', '')}"
    name = item.get("name", "")
    is_central = 1 if any(k in text for k in CENTRAL_KW) else 0
    is_planning = 1 if any(k in name for k in PURE_PLANNING_KW) else 0
    is_quasi_a = 1 if (is_b and any(k in name for k in HIGH_PROB_A_KW)) else 0
    if is_b:
        item["quasi_a"] = bool(is_quasi_a)
    return (is_quasi_a, is_central, is_planning, -int(item.get("idx", 0)))


def fetch_json(url: str, retries: int = 3):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 3.5 * (attempt + 1)
                print(f"[429] Rate limited, sleeping {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception:
            if attempt < retries:
                time.sleep(2.0)
                continue
            raise


def fetch_all_by_date(date_str: str):
    records = []
    page = 1
    while True:
        url = f"{BASE_URL}/listbydate?date={date_str}&page={page}"
        data = fetch_json(url)
        recs = data.get("records", [])
        if not recs:
            break
        records.extend(recs)
        total_pages = data.get("total_pages", 1)
        print(f"Fetched list page {page}/{total_pages} ({len(recs)} records)", file=sys.stderr)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.4)
    return records


def parse_roc_datetime(roc_str: str):
    """Parse '115/12/03 09:00' -> datetime(2026, 12, 3, 9, 0) or None."""
    m = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?", roc_str or "")
    if not m:
        return None
    year = int(m.group(1)) + 1911
    month = int(m.group(2))
    day = int(m.group(3))
    hour = int(m.group(4)) if m.group(4) else 23
    minute = int(m.group(5)) if m.group(5) else 59
    try:
        return datetime.datetime(year, month, day, hour, minute)
    except ValueError:
        return None


def parse_ntd(val: str) -> int:
    m = re.search(r"([\d,]+)", val or "")
    return int(m.group(1).replace(",", "")) if m else 0


def extract_detail_fields(detail_json):
    """Extract from the LATEST active tender (招標) record."""
    recs = detail_json.get("records", [])
    # Prefer latest non-award record
    target_rec = None
    for rec in reversed(recs):
        rtype = (rec.get("brief", {}) or {}).get("type", "")
        if not any(ex in rtype for ex in EXCLUDED_TYPES):
            target_rec = rec
            break
    if not target_rec and recs:
        target_rec = recs[-1]

    info = {
        "unit_name": "",
        "contact": "",
        "phone": "",
        "email": "",
        "address": "",
        "budget": "",
        "pub_date": "",
        "end_date": "",
        "award_method": "",
        "performance_bond": "",
        "bid_bond": "",
        "doc_fee": "",
        "pcc_url": "",
    }
    if not target_rec:
        return info

    d = target_rec.get("detail", {}) or {}

    info["unit_name"] = str(d.get("機關資料:單位名稱", "")).strip()
    info["contact"] = str(d.get("機關資料:聯絡人", "")).strip()
    info["phone"] = str(d.get("機關資料:聯絡電話", "")).strip()
    info["email"] = str(d.get("機關資料:電子郵件信箱", "")).strip()
    info["address"] = str(d.get("機關資料:機關地址", "")).strip()
    info["budget"] = str(d.get("採購資料:預算金額", "")).strip()
    info["pub_date"] = str(d.get("招標資料:公告日", "")).strip()
    info["end_date"] = str(d.get("領投開標:截止投標", "")).strip()
    info["award_method"] = str(d.get("招標資料:決標方式", "")).strip()
    info["performance_bond"] = str(
        d.get("領投開標:是否須繳納履約保證金", d.get("領投開標:履約保證金", ""))
    ).strip()
    info["bid_bond"] = str(
        d.get("領投開標:是否須繳納押標金", d.get("領投開標:押標金", ""))
    ).strip()
    info["qualification"] = str(
        d.get("廠商資格摘要", d.get("投標廠商資格:基本資格", ""))
    ).strip()

    # Accurately get total electronic tender fee (機關文件費 + 系統使用費 + 文件代收費)
    total_fee = str(d.get("領投開標:是否提供電子領標:總計", "")).strip()
    if total_fee:
        info["doc_fee"] = total_fee
    else:
        org_fee = parse_ntd(str(d.get("領投開標:是否提供電子領標:機關文件費(機關實收)", "")))
        sys_fee = parse_ntd(str(d.get("領投開標:是否提供電子領標:系統使用費", "")))
        agt_fee = parse_ntd(str(d.get("領投開標:是否提供電子領標:文件代收費", "")))
        if org_fee or sys_fee or agt_fee:
            info["doc_fee"] = f"{org_fee + sys_fee + agt_fee}元"

    detail_url = str(d.get("url", "")).strip()
    if detail_url.startswith("https://web.pcc.gov.tw"):
        info["pcc_url"] = detail_url

    return info


def pick_gemini_model(api_key: str) -> str:
    """Dynamically pick the newest available Gemini Flash/Pro model supporting generateContent."""
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(api_key)}"
    req = urllib.request.Request(list_url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    candidates = []
    for m in data.get("models", []):
        name = m.get("name", "")  # e.g. "models/gemini-2.5-flash"
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        low = name.lower()
        if "gemini" not in low:
            continue
        if any(bad in low for bad in ("embedding", "aqa", "imagen", "veo", "tts", "audio", "robotics", "computer-use")):
            continue
        score = 0
        if "flash" in low:
            score += 100
        if "lite" in low:
            score -= 10
        if "exp" in low or "preview" in low:
            score -= 5
        candidates.append((score, name))
    candidates.sort(reverse=True)
    if not candidates:
        raise RuntimeError("No generateContent Gemini model found for this API key")
    print(f"Using Gemini model: {candidates[0][1]}", file=sys.stderr)
    return candidates[0][1]


def gemini_semantic_review(candidates: list[dict], api_key: str) -> dict:
    """Use Gemini API to semantically re-classify A and top B candidates."""
    if not api_key or not candidates:
        return {}

    compact = [
        {"cno": x["cno"], "org": x["org"], "name": x["name"], "cat": x.get("category", ""), "cur": x["grade"]}
        for x in candidates
    ]
    prompt = (
        "你是九澍有限公司（台中）的政府標案審查專家。請嚴格依以下規則，對每筆標案重新判定 grade（A / B / C）與一句話 reason：\n"
        "【A 類（高潛力）】：九澍核心業務＝企劃、規劃、策展、展覽、活動企劃與執行、藝術節、音樂季、地方創生、文化行銷、非工程顧問研究。\n"
        "【C 類（必須無情排除）】：醫學/醫療/長照/社工/性侵害、生態/濕地/碳匯/環工、地政/GIS圖資、青創/創業育成/就業輔導/電商基地、電子票務/網站建置/軟體開發/維運、教育推廣/課程/培力/觀摩參訪/表演、純印刷出版、工程建築設計監造、手冊/指引/調查評估。\n"
        "【B 類（待確認）】：僅名稱含製作/拍攝/佈置且無法確定是否含核心企劃者。\n"
        "請輸出 JSON 陣列，每筆格式：{\"cno\":\"...\",\"grade\":\"A|B|C\",\"reason\":\"...\"}。\n"
        f"標案清單：\n{json.dumps(compact, ensure_ascii=False)}"
    )

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }).encode("utf-8")

    try:
        model_name = pick_gemini_model(api_key)
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={urllib.parse.quote(api_key)}"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        text = res["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        return {str(item["cno"]): item for item in parsed if isinstance(item, dict) and "cno" in item}
    except Exception as e:
        print(f"[Gemini fallback] {e}", file=sys.stderr)
        return {}


def main():
    parser = argparse.ArgumentParser(description="Fetch and filter today's active service tenders via PCC Open Data API")
    parser.add_argument("--date", default=datetime.date.today().strftime("%Y%m%d"), help="YYYYMMDD (default: today)")
    parser.add_argument("--out-dir", default="/Users/paul/Desktop/服務建議書/jiushu-site/data", help="Output data directory")
    parser.add_argument("--max-details", type=int, default=500, help="Max A+B tenders to fetch full details for")
    args = parser.parse_args()

    date_str = args.date.replace("-", "")
    iso_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    target_dt = datetime.datetime.strptime(date_str, "%Y%m%d")
    roc_today = f"{target_dt.year - 1911}/{target_dt.month:02d}/{target_dt.day:02d}"
    now_dt = datetime.datetime.now()

    out_dir = Path(args.out_dir)
    archive_dir = out_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Remove previous days' archive files so only today's data is kept
    for old_f in archive_dir.glob("*.json"):
        if not old_f.name.startswith(iso_date):
            old_f.unlink(missing_ok=True)

    print(f"=== Fetching active 勞務類 tenders for {iso_date} (ROC {roc_today}) ===", file=sys.stderr)
    raw_records = fetch_all_by_date(date_str)

    # Strictly keep ONLY: (1) 勞務類 AND (2) active 招標公告 (exclude 決標/無法決標/公開閱覽/預告)
    service_records = []
    for r in raw_records:
        brief = r.get("brief", {}) or {}
        cat = brief.get("category", "")
        rtype = brief.get("type", "")
        if "勞務類" not in cat:
            continue
        if any(ex in rtype for ex in EXCLUDED_TYPES):
            continue
        service_records.append(r)

    (archive_dir / f"{iso_date}_raw.json").write_text(
        json.dumps(service_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    a_list, b_list, c_list = [], [], []
    seen = set()

    for idx, r in enumerate(service_records, 1):
        unit_id = r.get("unit_id", "")
        job_no = r.get("job_number", "")
        key = (unit_id, job_no)
        if key in seen:
            continue
        seen.add(key)

        brief = r.get("brief", {}) or {}
        cat = brief.get("category", "")
        title = brief.get("title", "")
        org = r.get("unit_name", "")
        rtype = brief.get("type", "")

        t_obj = {
            "idx": str(idx),
            "org": org,
            "cno": job_no,
            "name": title,
            "method_raw": rtype,
            "budget": "",
            "pub_date": iso_date,
            "end_date": "",
            "url": "",
        }
        # Strict SKILL.md C-class checks before classify_tender
        if any(code in cat for code in STRICT_C_CAT_CODES):
            grade, reason = "C", f"非九澍服務類別（{cat.split('-')[0]}）"
        elif any(kw in title for kw in STRICT_C_NAME_KW):
            grade, reason = "C", "名稱含 SKILL 排除詞（手冊/指引/調查評估/維護/維運/檢驗等）"
        else:
            grade, reason = classify_tender(t_obj)
        entry = {
            "idx": idx,
            "date": iso_date,
            "unit_id": unit_id,
            "org": org,
            "cno": job_no,
            "name": title,
            "category": cat,
            "method": rtype,
            "grade": grade,
            "reason": reason,
        }
        if grade == "A":
            a_list.append(entry)
        elif grade == "B":
            b_list.append(entry)
        else:
            c_list.append(entry)

    # Pre-sort B so top priority B candidates are included in Gemini semantic review
    b_list = sorted(b_list, key=lambda x: score_priority(x, is_b=True), reverse=True)

    # Optional Gemini AI semantic review (if GEMINI_API_KEY is set)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key:
        review_pool = a_list + b_list[:120]
        ai_decisions = gemini_semantic_review(review_pool, api_key)
        if ai_decisions:
            new_a, new_b = [], list(b_list[120:])
            for item in review_pool:
                dec = ai_decisions.get(item["cno"])
                if dec and dec.get("grade") in ("A", "B", "C"):
                    item["grade"] = dec["grade"]
                    item["reason"] = f"AI｜{dec.get('reason', item['reason'])}"
                if item["grade"] == "A":
                    new_a.append(item)
                elif item["grade"] == "B":
                    new_b.append(item)
                else:
                    c_list.append(item)
            a_list, b_list = new_a, new_b
            print(f"Gemini AI review applied: A={len(a_list)}, B={len(b_list)}, C={len(c_list)}", file=sys.stderr)

    # Fetch full details for ALL A-class AND B-class tenders (up to max_details)
    # so every A and B card has budget, deadline, doc_fee, phone, and bond checks
    verified_a = []
    verified_b = []
    combined_targets = a_list + b_list
    for item in combined_targets[: max(args.max_details, len(a_list))]:
        orig_grade = item["grade"]
        try:
            detail_url = f"{BASE_URL}/tender?unit_id={urllib.parse.quote(item['unit_id'])}&job_number={urllib.parse.quote(item['cno'])}"
            detail_json = fetch_json(detail_url)
            info = extract_detail_fields(detail_json)
            item.update(info)

            # Check deadline not expired
            end_dt = parse_roc_datetime(item.get("end_date", ""))
            if end_dt and end_dt < now_dt:
                item["grade"] = "C"
                item["reason"] = f"已截止投標（{item.get('end_date', '')}）"
                c_list.append(item)
                time.sleep(0.35)
                continue

            # Check 履約保證金 & 押標金 hard rules
            pb = item.get("performance_bond", "")
            if pb and pb not in ("否", "無", "免", "免收"):
                item["grade"] = "C"
                item["reason"] = "使用者規則：須繳履約保證金"
                c_list.append(item)
                time.sleep(0.35)
                continue

            bb = item.get("bid_bond", "")
            if bb and bb not in ("否", "無", "免", "免收"):
                item["grade"] = "C"
                item["reason"] = "使用者規則：須繳押標金"
                c_list.append(item)
                time.sleep(0.35)
                continue

            # Check 最低標 (單純價格戰)
            am = item.get("award_method", "")
            if "最低標" in am and "最有利標" not in am:
                item["grade"] = "C"
                item["reason"] = "單純價格戰（最低標）"
                c_list.append(item)
                time.sleep(0.35)
                continue

            # Check 商業團體（公會）會員證明或特許事務所
            qual = item.get("qualification", "")
            if any(q in qual for q in ("同業公會", "公會會員", "技師事務所", "建築師事務所")):
                item["grade"] = "C"
                item["reason"] = "資格不符：需商業團體（公會）會員證明或特許事務所，九澍未加入"
                c_list.append(item)
                time.sleep(0.35)
                continue

            if orig_grade == "A":
                verified_a.append(item)
            else:
                verified_b.append(item)
            time.sleep(0.4)
        except Exception as e:
            item["detail_error"] = str(e)
            if orig_grade == "A":
                verified_a.append(item)
            else:
                verified_b.append(item)

    if len(combined_targets) > max(args.max_details, len(a_list)):
        for leftover in combined_targets[max(args.max_details, len(a_list)):]:
            if leftover["grade"] == "B":
                verified_b.append(leftover)

    a_list = sorted(verified_a, key=lambda x: score_priority(x, is_b=False), reverse=True)
    b_list = sorted(verified_b, key=lambda x: score_priority(x, is_b=True), reverse=True)

    classified_archive = {
        "date": iso_date,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "total": len(a_list) + len(b_list) + len(c_list),
            "A": len(a_list),
            "B": len(b_list),
            "C": len(c_list),
        },
        "A": a_list,
        "B": b_list,
        "C": c_list,
    }
    (archive_dir / f"{iso_date}_classified.json").write_text(
        json.dumps(classified_archive, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    daily_payload = {
        "date": iso_date,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": classified_archive["summary"],
        "A": a_list,
        "B": b_list,
        "archive_ref": f"data/archive/{iso_date}_classified.json",
    }
    (out_dir / "daily_tenders.json").write_text(
        json.dumps(daily_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(classified_archive["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
