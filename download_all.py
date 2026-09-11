#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, re, json, pathlib, traceback
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://bgc.eshiksabd.com"
OUTPUT = pathlib.Path("/Users/th28/BGC/Student receipt")
OUTPUT.mkdir(parents=True, exist_ok=True)
LOG = pathlib.Path("/Users/th28/BGC/download_all.log")

students = json.load(open("/Users/th28/BGC/students.json", encoding="utf-8"))
total = len(students)
print(f"Total students to process: {total}")
print(f"Output dir: {OUTPUT}")
# Check already done
existing = set(p.name for p in OUTPUT.glob("*.pdf"))
print(f"Already have {len(existing)} files")

def sanitize(n):
    # Remove invalid filesystem chars
    invalid = '<>:"/\\|?*'
    for c in invalid:
        n = n.replace(c, "_")
    # Collapse whitespace, trim
    n = " ".join(n.split())
    return n

def parse_date(s):
    months = {"Jan":0,"Feb":1,"Mar":2,"Apr":3,"May":4,"Jun":5,"Jul":6,"Aug":7,"Sep":8,"Oct":9,"Nov":10,"Dec":11}
    p=s.split("-")
    if len(p)!=3:
        raise ValueError(f"bad date {s}")
    return datetime(int(p[2]), months[p[1]], int(p[0]))

def login(page):
    print("Logging in as bgcstudent...")
    page.goto(f"{BASE}/main", wait_until="networkidle", timeout=30000)
    time.sleep(1)
    # Check if already logged in (redirected to Result-Enquiry-Center)
    if "Student Information Center" in page.title():
        print("Already logged in")
        return True
    # Fill
    try:
        page.get_by_role("textbox", name="User ID").fill("bgcstudent")
        page.get_by_role("textbox", name="Password").fill("bgcstudent")
        page.get_by_role("button", name="Sign In").click()
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)
        print(f"After login: {page.title()} {page.url}")
        if "Student Information Center" in page.title():
            print("Login successful")
            return True
        else:
            print("Login failed, page content snippet:", page.content()[:500])
            return False
    except Exception as e:
        print(f"Login exception: {e}")
        traceback.print_exc()
        return False

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        viewport={"width":1280,"height":800},
        locale="en-US"
    )
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    if not login(page):
        print("Initial login failed, exiting")
        browser.close()
        exit(1)

    # Ensure on Result-Enquiry-Center
    if "Result-Enquiry-Center" not in page.url:
        page.goto(f"{BASE}/Result-Enquiry-Center", wait_until="networkidle")
        time.sleep(1)

    success = 0
    skipped = 0
    failed = 0
    no_data = 0

    start_idx = 0
    # Find first not yet done? We'll just iterate all and skip existing
    for idx, entry in enumerate(students):
        sid = entry["id"]
        name = entry["name"]
        safe = sanitize(name)
        fname = f"{sid}_{safe}.pdf"
        fpath = OUTPUT / fname

        # Skip if exists and size >0
        if fpath.exists() and fpath.stat().st_size > 1000:
            skipped += 1
            if idx % 50 == 0:
                print(f"[{idx+1}/{total}] SKIP {sid} {name} (exists)")
            continue

        print(f"\n[{idx+1}/{total}] Processing {sid} {name} -> {fname}")
        # Retry loop
        for attempt in range(3):
            try:
                # Re-check login if needed: if html contains EMS Login, re-login
                html = page.evaluate("""async (sid) => {
                    const r = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                        method:'POST',
                        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                        body:`rootData=${sid}&flagreq=transactionCheck`
                    });
                    return await r.text();
                }""", sid)

                # Check for login redirect
                if "EMS Login" in html or "<title>EMS Login</title>" in html:
                    print(f"  ! Session expired / EMS Login detected, re-logging (attempt {attempt+1})")
                    if not login(page):
                        print("  Re-login failed")
                        time.sleep(2)
                        continue
                    # After re-login, retry the same sid
                    continue

                if "No transaction found" in html:
                    print(f"  ! No transaction found for {sid}, skipping")
                    no_data += 1
                    break

                if "<table" not in html:
                    snippet = html[:600].replace("\n"," ")[:300]
                    print(f"  ! No table, snippet: {snippet}")
                    # Might be error like "Class roll not found"
                    if "Error" in html or "not found" in html.lower():
                        print(f"  -> Class roll not found, skip")
                        no_data += 1
                        break
                    # Retry
                    if attempt < 2:
                        time.sleep(1)
                        continue
                    else:
                        failed += 1
                        break

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("tbody tr")
                if not rows:
                    print(f"  ! No rows")
                    no_data += 1
                    break
                parsed=[]
                for tr in rows:
                    tds=tr.find_all("td")
                    if len(tds)<7:
                        continue
                    sname=tds[0].get_text(strip=True)
                    dstr=tds[3].get_text(strip=True)
                    btn=tds[6].find("button")
                    onclick=btn.get("onclick") if btn else ""
                    m=re.search(r"printReceipts\((\d+)\)", onclick or "")
                    pid=m.group(1) if m else None
                    fee=tds[4].get_text(strip=True)
                    try:
                        dobj=parse_date(dstr)
                    except Exception as e:
                        print(f"    ! bad date {dstr}: {e}")
                        continue
                    if pid:
                        parsed.append({"sname":sname,"dstr":dstr,"dobj":dobj,"pid":pid,"fee":fee})
                if not parsed:
                    print(f"  ! No parsable rows")
                    no_data += 1
                    break

                # Filter by name matching
                norm = lambda s: " ".join(s.split()).lower()
                cand = [x for x in parsed if norm(x["sname"])==norm(name)]
                if cand:
                    # Found matching
                    pass
                else:
                    # Fallback to all, but log
                    print(f"  ! Warning: no row matched expected name '{name}', candidates: {[x['sname'] for x in parsed[:3]]}, using all")
                    cand = parsed

                latest = max(cand, key=lambda x: x["dobj"])
                print(f"  Found {len(parsed)} rows, filtered {len(cand)}, latest: {latest['dstr']} ({latest['fee']}) pid {latest['pid']}")

                # Encryption
                enc = page.evaluate("""async (pid) => {
                    const r = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                        method:'POST',
                        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                        body:`rootData=${pid}&flagreq=ajaxEncryption`
                    });
                    return (await r.text()).trim();
                }""", latest["pid"])

                if not enc or "Error" in enc or len(enc) < 10:
                    print(f"  ! Encryption failed: {enc[:200]}")
                    if attempt < 2:
                        time.sleep(1)
                        continue
                    failed += 1
                    break
                print(f"  Enc: {enc[:30]}...")

                pdf_url = f"{BASE}/std_coll_slip.php?xxCode={enc}"
                resp = context.request.get(pdf_url, headers={"Referer": f"{BASE}/Result-Enquiry-Center"})
                if resp.status != 200:
                    print(f"  ! PDF GET failed status {resp.status}")
                    print(resp.text()[:500])
                    if attempt < 2:
                        time.sleep(1)
                        continue
                    failed += 1
                    break
                body = resp.body()
                if b"%PDF" not in body[:30]:
                    # Check if it's actually HTML error
                    snippet = body[:500].decode(errors='ignore')
                    print(f"  ! Not PDF, snippet: {snippet[:300]}")
                    if attempt < 2:
                        time.sleep(1)
                        continue
                    failed += 1
                    break
                # Save
                with open(fpath, "wb") as f:
                    f.write(body)
                print(f"  ✓ Saved {fpath.name} ({len(body)} bytes) - Transaction {latest['dstr']} {latest['fee']}")
                success += 1
                # Log
                with open(LOG, "a", encoding="utf-8") as logf:
                    logf.write(f"{sid},{name},{latest['dstr']},{latest['fee']},{latest['pid']},{fpath.name},OK\n")
                time.sleep(0.8)  # polite delay
                break  # success, break retry loop

            except Exception as e:
                print(f"  ! Exception on attempt {attempt+1}: {e}")
                traceback.print_exc()
                if attempt < 2:
                    time.sleep(1)
                    # Try re-login if exception might be due to session
                    try:
                        if "Student Information Center" not in page.title():
                            login(page)
                    except:
                        pass
                    continue
                else:
                    failed += 1
                    with open(LOG, "a", encoding="utf-8") as logf:
                        logf.write(f"{sid},{name},ERROR,{e},FAIL\n")
                    break
        # End retry loop for this sid
        # Periodic status
        if (idx+1) % 20 == 0:
            print(f"\n--- Progress: {idx+1}/{total} | success={success} skipped={skipped} failed={failed} no_data={no_data} ---")
        # Small delay between students
        time.sleep(0.5)

    browser.close()
    print("\n" + "="*60)
    print(f"Done. Total: {total}, Success: {success}, Skipped (already existed): {skipped}, No data: {no_data}, Failed: {failed}")
    print(f"Output dir: {OUTPUT} contains {len(list(OUTPUT.glob('*.pdf')))} files")
    # Final verification
    with open(LOG, "a") as logf:
        logf.write(f"FINAL {total} {success} {skipped} {failed} {no_data}\n")
