#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import re
import time
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime
import os

BASE_URL = "https://bgc.eshiksabd.com"
RESULT_URL = f"{BASE_URL}/Result-Enquiry-Center"
CONTROLLER_URL = f"{BASE_URL}/controller_student_module.php"
OUTPUT_DIR = Path("/Users/th28/BGC/Student receipt")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STUDENTS = [
    ("1202425010001", "NAHIYAN MAHMOOD"),
    ("1202425010002", "S. M TAHSIN RAHMAN"),
    ("1202425010003", "MD. TAHSIN MAHDI PALLAB"),
    ("1202425010004", "MOHAMMED RAIZUL ISLAM RABAB"),
    ("1202425010005", "MD. TAHMIDUZZAMAN ANAS"),
]

def sanitize(name):
    invalid = '<>:"/\\|?*'
    for c in invalid:
        name = name.replace(c, "_")
    return " ".join(name.split())

def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y")
    except:
        return None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    print(f"Goto {RESULT_URL}")
    for attempt in range(3):
        page.goto(RESULT_URL, wait_until="networkidle", timeout=30000)
        print(f"Attempt {attempt+1}: Title: {page.title()}, URL: {page.url}")
        page.wait_for_timeout(1500)
        if "Student Information Center" in page.title() or "Result-Enquiry-Center" in page.url:
            print("Reached Student Information Center")
            break
        else:
            print(f"  Got EMS Login, retrying... (attempt {attempt+1})")
            page.wait_for_timeout(1000)
            # Sometimes need to hit main first then retry
            continue
    print(f"Final Title: {page.title()}, URL: {page.url}")
    page.wait_for_timeout(1000)
    # Ensure jQuery loaded
    # Click Receipts Print to ensure tab JS is initialized (though not strictly needed for AJAX)
    try:
        page.get_by_role("button", name="Receipts Print").click()
        page.wait_for_timeout(1000)
        print("Clicked Receipts Print tab")
    except Exception as e:
        print(f"Click Receipts Print failed: {e}")

    for sid, name in STUDENTS:
        safe = sanitize(name)
        filename = f"{sid}_{safe}.pdf"
        filepath = OUTPUT_DIR / filename
        print(f"\n=== {sid} {name} -> {filepath} ===")
        if filepath.exists():
            print(" Already exists, skip")
            continue

        # Step 1: transactionCheck via page.evaluate fetch
        # Use page.evaluate to run fetch inside browser context
        try:
            html = page.evaluate("""async (sid) => {
                const resp = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: `rootData=${sid}&flagreq=transactionCheck`
                });
                const text = await resp.text();
                return text;
            }""", sid)
            print(f" HTML len {len(html)}")
            if "Error" in html or "<table" not in html:
                snippet = html[:500].replace("\n"," ")
                print(f"  No table, snippet: {snippet}")
                if "Error" in html:
                    print("  Error in response")
                continue
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tbody tr")
            print(f"  Found {len(rows)} rows")
            parsed = []
            for idx, tr in enumerate(rows):
                tds = tr.find_all("td")
                if len(tds) < 7:
                    continue
                student_name = tds[0].get_text(strip=True)
                trans_date_str = tds[3].get_text(strip=True)
                btn = tds[6].find("button")
                onclick = btn.get("onclick") if btn else ""
                m = re.search(r"printReceipts\((\d+)\)", onclick or "")
                print_id = m.group(1) if m else None
                date_obj = parse_date(trans_date_str)
                fee_type = tds[4].get_text(strip=True)
                amount = tds[5].get_text(strip=True)
                print(f"   Row {idx}: {student_name} | {trans_date_str} | {fee_type} | {amount} | printId={print_id}")
                if date_obj and print_id:
                    parsed.append({
                        "student_name": student_name,
                        "date_str": trans_date_str,
                        "date_obj": date_obj,
                        "print_id": print_id,
                    })
            if not parsed:
                print("  No parsable rows")
                continue
            # Filter by name matching
            expected_norm = " ".join(name.split()).lower()
            matching = [p for p in parsed if " ".join(p["student_name"].split()).lower() == expected_norm]
            candidates = matching if matching else parsed
            if matching:
                print(f"  Filtered matching {len(matching)} rows")
            else:
                print(f"  No matching name, using all {len(parsed)} rows")
            latest = max(candidates, key=lambda x: x["date_obj"])
            print(f"  Latest: {latest['date_str']} printId={latest['print_id']}")

            # Step 2: ajaxEncryption
            enc = page.evaluate("""async (printId) => {
                const resp = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: `rootData=${printId}&flagreq=ajaxEncryption`
                });
                const text = await resp.text();
                return text.trim();
            }""", latest["print_id"])
            print(f"  Enc code: {enc}")
            if not enc or "Error" in enc:
                print("  Encryption failed")
                continue

            # Step 3: Download PDF via context request (shares cookies)
            pdf_url = f"{BASE_URL}/std_coll_slip.php?xxCode={enc}"
            print(f"  GET PDF {pdf_url}")
            # Use APIRequestContext from context
            # context.request is available
            resp = context.request.get(pdf_url, headers={"Referer": RESULT_URL})
            print(f"  PDF status {resp.status}, headers {resp.headers.get('content-type')}, len via header {resp.headers.get('content-length')}")
            if resp.status != 200:
                print(f"  Failed PDF fetch status {resp.status}")
                print(resp.text()[:500])
                continue
            body = resp.body()
            print(f"  PDF body len {len(body)}, starts {body[:10]}")
            if not body.startswith(b"%PDF"):
                print(f"  Not PDF! First 500: {body[:500]}")
                continue
            # Save
            with open(filepath, "wb") as f:
                f.write(body)
            print(f"  ✓ Saved {filepath} ({len(body)} bytes)")
            time.sleep(1)

        except Exception as e:
            print(f"  Exception: {e}")
            import traceback
            traceback.print_exc()
            continue

    browser.close()
    print("\nDone")
    # List output
    for pth in OUTPUT_DIR.glob("*.pdf"):
        print(f" - {pth.name} {pth.stat().st_size} bytes")
