#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, re, json, pathlib, traceback, base64
from pypdf import PdfReader

BASE = "https://result19.comillaboard.gov.bd/2420s/individual"
INDEX_URL = f"{BASE}/index_reg1.php"
OUTPUT_ROOT = pathlib.Path("/Users/th28/BGC/student-data")
SRC_RECEIPT_ROOT = pathlib.Path("/Users/th28/BGC/Student receipt")
students = json.load(open("/Users/th28/BGC/students.json", encoding="utf-8"))

# Use cached mapping to avoid re-reading PDFs (slow)
def sanitize(name):
    return " ".join(name.split()).replace(" ", "-")

# Load cached roll/reg
roll_reg_map = json.load(open("/Users/th28/BGC/roll_reg_map.json", encoding="utf-8"))
def get_roll_reg_from_receipt(pdf_path):
    # Fallback if needed, but we use cached
    try:
        sid = pdf_path.stem.split("_")[0]
        if sid in roll_reg_map:
            return roll_reg_map[sid]["roll"], roll_reg_map[sid]["reg"], ""
        # Fallback to reading PDF
        r = PdfReader(str(pdf_path))
        txt = r.pages[0].extract_text() or ""
        adm = re.search(r"Admission Roll:\s*([0-9]+)", txt)
        reg = re.search(r"SSC/HSC Reg\. No\.:\s*([0-9]+)", txt)
        return adm.group(1).strip() if adm else None, reg.group(1).strip() if reg else None, txt
    except Exception as e:
        print(f"  Error reading {pdf_path}: {e}")
        return None, None, ""

total = len(students)
print(f"Total students: {total}")
print(f"Output root: {OUTPUT_ROOT}")
print(f"Index URL: {INDEX_URL}")

# Count already done SSC
already_ssc = list(OUTPUT_ROOT.rglob("*SSC*.pdf"))
print(f"Already have SSC PDFs: {len(already_ssc)}")
for p in already_ssc[:3]:
    print(f"  {p}")

# Prepare list of remaining
remaining = []
for entry in students:
    sid = entry["id"]
    name = entry["name"]
    safe_folder = sanitize(f"{sid}_{name}")
    # The SSC file we will save is with hyphens: f"{sid}_{sanitize(name)}_SSC_2024.pdf" but sanitize already does spaces->-
    # Actually for file name, we want to keep original spaces for the fee receipt, but for SSC we use hyphens as per Option A
    # Let's use: f"{sid}_{sanitize(name)}_SSC_2024.pdf" where sanitize does spaces->-
    ssc_fname = f"{sid}_{sanitize(name)}_SSC_2024.pdf"
    ssc_path = OUTPUT_ROOT / safe_folder / ssc_fname
    # Also check alternative naming with spaces (in case previous test used that)
    alt_path = OUTPUT_ROOT / safe_folder / f"{sid}_{name}_SSC_2024.pdf"
    if ssc_path.exists() or alt_path.exists():
        continue
    # Check if receipt exists to get roll/reg
    # Find receipt pdf in Student receipt
    # Receipt is named like "1202425010001_NAHIYAN MAHMOOD.pdf" with spaces
    receipt_candidates = list(SRC_RECEIPT_ROOT.glob(f"{sid}_*.pdf"))
    if not receipt_candidates:
        print(f"  No receipt for {sid} {name}, skipping")
        continue
    receipt_pdf = receipt_candidates[0]
    roll, reg, txt = get_roll_reg_from_receipt(receipt_pdf)
    if not roll or not reg:
        print(f"  {sid} {name}: missing roll ({roll}) or reg ({reg}), skipping (blank)")
        continue
    remaining.append((sid, name, roll, reg, ssc_path))

print(f"Remaining to download: {len(remaining)}")
for sid, name, roll, reg, ssc_path in remaining[:5]:
    print(f"  {sid} {name} -> Roll {roll} Reg {reg} -> {ssc_path}")

# Now start playwright
LOG = pathlib.Path("/Users/th28/BGC/ssc_download.log")
LOG.write_text(f"Start {time.ctime()} total {total} remaining {len(remaining)}\n", encoding="utf-8")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        viewport={"width":1280,"height":800}
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    # Initial goto
    print(f"Goto {INDEX_URL}")
    page.goto(INDEX_URL, wait_until="networkidle", timeout=30000)
    time.sleep(1)
    print(f"Title: {page.title()} URL: {page.url}")

    success = 0
    failed = 0
    not_found = 0

    for idx, (sid, name, roll, reg, ssc_path) in enumerate(remaining):
        print(f"\n[{idx+1}/{len(remaining)}] {sid} {name} Roll:{roll} Reg:{reg}")
        # Ensure we are on index page
        if "index_reg1.php" not in page.url:
            page.goto(INDEX_URL, wait_until="networkidle")
            time.sleep(1)
        
        # Fill form
        try:
            # The form has two textboxes: "Enter SSC Roll" and "Enter SSC Reg. No."
            # UseSelectors
            page.get_by_role("textbox", name="Enter SSC Roll").fill(roll)
            page.get_by_role("textbox", name="Enter SSC Reg. No.").fill(reg)
            time.sleep(0.5)
            page.get_by_role("button", name="Submit").click()
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(1)
            
            # Check result
            content = page.content()
            if "SSC Result 2024" in content and "Roll No" in content:
                # Verify roll matches (check roll is in content)
                if roll in content:
                    # Save PDF
                    ssc_path.parent.mkdir(parents=True, exist_ok=True)
                    page.pdf(path=str(ssc_path), format="A4")
                    print(f"  ✓ Saved {ssc_path.name} ({ssc_path.stat().st_size} bytes)")
                    success += 1
                    with open(LOG, "a", encoding="utf-8") as lf:
                        lf.write(f"{sid},{name},{roll},{reg},{ssc_path.name},OK\n")
                    page.goto(INDEX_URL, wait_until="networkidle")
                    time.sleep(0.8)
                else:
                    print(f"  ! Roll mismatch, snippet: {content[:500]}")
                    failed += 1
                    with open(LOG, "a", encoding="utf-8") as lf:
                        lf.write(f"{sid},{name},{roll},{reg},MISMATCH,FAIL\n")
                    page.goto(INDEX_URL, wait_until="networkidle")
                    time.sleep(0.8)
            elif "Result Not Found" in content or "not found" in content.lower() or "Wrong" in content or "No Result" in content:
                print(f"  ! Not found / Wrong, snippet: {content[:500]}")
                not_found += 1
                with open(LOG, "a", encoding="utf-8") as lf:
                    lf.write(f"{sid},{name},{roll},{reg},NOT_FOUND,SKIP\n")
                page.goto(INDEX_URL, wait_until="networkidle")
                time.sleep(0.8)
            else:
                snippet = content[:2000]
                print(f"  ! Unknown result, snippet: {snippet[:500]}")
                if "SSC Roll" in content and "SSC Reg" in content:
                    print(f"  Still on form")
                    failed += 1
                    with open(LOG, "a", encoding="utf-8") as lf:
                        lf.write(f"{sid},{name},{roll},{reg},STILL_FORM,FAIL\n")
                else:
                    failed += 1
                    with open(LOG, "a", encoding="utf-8") as lf:
                        lf.write(f"{sid},{name},{roll},{reg},UNKNOWN,FAIL\n")
                page.goto(INDEX_URL, wait_until="networkidle")
                time.sleep(0.8)
                
        except Exception as e:
            print(f"  Exception: {e}")
            traceback.print_exc()
            failed += 1
            with open(LOG, "a", encoding="utf-8") as lf:
                lf.write(f"{sid},{name},{roll},{reg},EXCEPTION,{e}\n")
            try:
                page.goto(INDEX_URL, wait_until="networkidle")
                time.sleep(1)
            except:
                pass
        
        if (idx+1) % 20 == 0:
            print(f"\n--- Progress {idx+1}/{len(remaining)} success={success} failed={failed} not_found={not_found} ---")
        # Polite delay
        time.sleep(0.7)

    browser.close()
    print(f"\nDone. Total remaining {len(remaining)} Success {success} Failed {failed} NotFound {not_found}")
    print(f"Total SSC PDFs now: {len(list(OUTPUT_ROOT.rglob('*SSC*.pdf')))}")
    with open(LOG, "a") as lf:
        lf.write(f"FINAL {len(remaining)} {success} {failed} {not_found}\n")
