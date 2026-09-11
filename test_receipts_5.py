#!/usr/bin/env python3
import requests
import re
import os
import time
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# Config
BASE_URL = "https://bgc.eshiksabd.com"
RESULT_URL = f"{BASE_URL}/Result-Enquiry-Center"
CONTROLLER_URL = f"{BASE_URL}/controller_student_module.php"
OUTPUT_DIR = Path("/Users/th28/BGC/Student receipt")

# Mapping for first 5 - skip missing numbers
STUDENTS = [
    ("1202425010001", "NAHIYAN MAHMOOD"),
    ("1202425010002", "S. M TAHSIN RAHMAN"),
    ("1202425010003", "MD. TAHSIN MAHDI PALLAB"),
    ("1202425010004", "MOHAMMED RAIZUL ISLAM RABAB"),
    ("1202425010005", "MD. TAHMIDUZZAMAN ANAS"),
]

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    "Referer": RESULT_URL,
    "Accept": "*/*",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

def sanitize_filename(name):
    # Replace invalid chars
    invalid = '<>:"/\\|?*'
    for c in invalid:
        name = name.replace(c, "_")
    # Strip extra spaces
    name = " ".join(name.split())
    return name

def parse_date(date_str):
    try:
        return datetime.strptime(date_str.strip(), "%d-%b-%Y")
    except Exception as e:
        print(f"  ! Failed to parse date '{date_str}': {e}")
        return None

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
session = requests.Session()
session.headers.update({"User-Agent": headers["User-Agent"]})

# Initial GET to get cookies/session
print(f"GET {RESULT_URL} to establish session...")
try:
    r = session.get(RESULT_URL, headers={"User-Agent": headers["User-Agent"]}, timeout=15)
    print(f" Session cookies: {session.cookies.get_dict()}")
    print(f" GET status: {r.status_code}")
except Exception as e:
    print(f"Failed initial GET: {e}")
    exit(1)

for sid, name in STUDENTS:
    safe_name = sanitize_filename(name)
    filename = f"{sid}_{safe_name}.pdf"
    filepath = OUTPUT_DIR / filename
    print(f"\n=== Processing {sid} {name} ===")
    print(f" Target: {filepath}")

    if filepath.exists():
        print(f"  Already exists, skipping...")
        continue

    # Step 1: transactionCheck
    data = {"rootData": sid, "flagreq": "transactionCheck"}
    try:
        resp = session.post(CONTROLLER_URL, data=data, headers=headers, timeout=15)
        print(f"  POST transactionCheck status={resp.status_code}, len={len(resp.text)}")
        # print(resp.text[:2000])
        if "Error" in resp.text or "Class roll not found" in resp.text:
            print(f"  ! Error or not found for {sid}, skipping")
            continue
        if "<table" not in resp.text:
            print(f"  ! No table found, response: {resp.text[:500]}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("tbody tr")
        if not rows:
            print(f"  ! No rows found")
            continue
        print(f"  Found {len(rows)} payment rows")

        # Parse rows
        parsed = []
        for idx, tr in enumerate(rows):
            tds = tr.find_all("td")
            if len(tds) < 7:
                continue
            student_name = tds[0].get_text(strip=True)
            bank = tds[1].get_text(strip=True)
            trans_no = tds[2].get_text(strip=True)
            trans_date_str = tds[3].get_text(strip=True)
            fee_type = tds[4].get_text(strip=True)
            amount = tds[5].get_text(strip=True)
            btn = tds[6].find("button")
            onclick = btn.get("onclick") if btn else ""
            m = re.search(r"printReceipts\((\d+)\)", onclick or "")
            print_id = m.group(1) if m else None
            date_obj = parse_date(trans_date_str)
            print(f"   Row {idx}: {student_name} | {trans_date_str} | {fee_type} | {amount} | printId={print_id}")
            if date_obj and print_id:
                parsed.append({
                    "student_name": student_name,
                    "date_str": trans_date_str,
                    "date_obj": date_obj,
                    "print_id": print_id,
                    "fee_type": fee_type,
                    "trans_no": trans_no,
                })
        if not parsed:
            print(f"  ! No parsable rows")
            continue

        # Filter to only rows matching expected name? Let's see exact matching logic.
        # User said list is for "my student" - so we expect student_name matches name.
        # But to be safe, prefer matching rows; if none match, use all.
        expected_norm = " ".join(name.split()).lower()
        matching = [p for p in parsed if " ".join(p["student_name"].split()).lower() == expected_norm]
        # Also handle case where expected has extra spaces like "MD. TAHSIN MAHDI PALLAB" vs table maybe has line break? Normalize.
        # If filtering removes all, fallback to all.
        candidates = matching if matching else parsed
        if matching:
            print(f"  Filtered to {len(matching)} rows matching expected name")
        else:
            print(f"  ! No rows matched expected name '{name}', using all {len(parsed)} rows (might be data issue)")

        # Pick latest by date
        latest = max(candidates, key=lambda x: x["date_obj"])
        print(f"  -> Latest: {latest['date_str']} (printId={latest['print_id']}, fee={latest['fee_type']})")

        # Step 2: ajaxEncryption
        data2 = {"rootData": latest["print_id"], "flagreq": "ajaxEncryption"}
        resp2 = session.post(CONTROLLER_URL, data=data2, headers=headers, timeout=15)
        print(f"  POST ajaxEncryption status={resp2.status_code}, body={resp2.text[:200]}")
        enc = resp2.text.strip()
        if not enc or "Error" in enc:
            print(f"  ! Encryption failed")
            continue
        # enc should be base64-like
        print(f"  Encrypted code: {enc}")

        # Step 3: GET pdf
        pdf_url = f"{BASE_URL}/std_coll_slip.php?xxCode={enc}"
        print(f"  GET PDF {pdf_url}")
        # Use same session, headers for PDF (no X-Requested-With)
        pdf_headers = {
            "User-Agent": headers["User-Agent"],
            "Referer": RESULT_URL,
        }
        resp3 = session.get(pdf_url, headers=pdf_headers, timeout=20)
        print(f"  PDF response status={resp3.status_code}, content-type={resp3.headers.get('content-type')}, len={len(resp3.content)}")
        if resp3.headers.get("content-type") != "application/pdf":
            # Might be html error
            print(f"  ! Not a PDF, first 500 chars: {resp3.text[:500]}")
            continue
        # Check for PDF magic
        if not resp3.content.startswith(b"%PDF"):
            print(f"  ! Content not PDF magic, first 20 bytes: {resp3.content[:20]}")
            continue

        # Save
        with open(filepath, "wb") as f:
            f.write(resp3.content)
        print(f"  ✓ Saved to {filepath} ({len(resp3.content)} bytes)")

        # Be nice, delay 1 sec
        time.sleep(1)

    except Exception as e:
        print(f"  ! Exception for {sid}: {e}")
        import traceback
        traceback.print_exc()
        time.sleep(1)
        continue

print("\n=== Done ===")
print(f"Check output dir: {OUTPUT_DIR}")
for p in OUTPUT_DIR.glob("*.pdf"):
    print(f" - {p.name} ({p.stat().st_size} bytes)")
