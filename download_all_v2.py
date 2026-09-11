#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, re, json, pathlib, traceback, base64
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://bgc.eshiksabd.com"
OUTPUT = pathlib.Path("/Users/th28/BGC/Student receipt")
OUTPUT.mkdir(parents=True, exist_ok=True)
LOG = pathlib.Path("/Users/th28/BGC/download_all.log")

students = json.load(open("/Users/th28/BGC/students.json", encoding="utf-8"))
total = len(students)
print(f"Total students: {total}, already have {len(list(OUTPUT.glob('*.pdf')))} files", flush=True)

def sanitize(n):
    invalid = '<>:"/\\|?*'
    for c in invalid:
        n = n.replace(c, "_")
    return " ".join(n.split())

def parse_date(s):
    months = {"Jan":0,"Feb":1,"Mar":2,"Apr":3,"May":4,"Jun":5,"Jul":6,"Aug":7,"Sep":8,"Oct":9,"Nov":10,"Dec":11}
    p=s.split("-")
    return datetime(int(p[2]), months[p[1]], int(p[0]))

def login(page):
    print("Logging in...", flush=True)
    page.goto(f"{BASE}/main", wait_until="networkidle", timeout=30000)
    time.sleep(1)
    if "Student Information Center" in page.title():
        print("Already logged in", flush=True)
        return True
    try:
        page.get_by_role("textbox", name="User ID").fill("bgcstudent")
        page.get_by_role("textbox", name="Password").fill("bgcstudent")
        page.get_by_role("button", name="Sign In").click()
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)
        print(f"After login: {page.title()} {page.url}", flush=True)
        return "Student Information Center" in page.title()
    except Exception as e:
        print(f"Login exception: {e}", flush=True)
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
        print("Initial login failed", flush=True)
        browser.close()
        exit(1)
    if "Result-Enquiry-Center" not in page.url:
        page.goto(f"{BASE}/Result-Enquiry-Center", wait_until="networkidle")
        time.sleep(1)

    success = 0
    skipped = 0
    failed = 0
    no_data = 0

    # Count already existing
    existing_files = set(f.name for f in OUTPUT.glob("*.pdf"))
    print(f"Skipping {len(existing_files)} existing", flush=True)

    for idx, entry in enumerate(students):
        sid = entry["id"]
        name = entry["name"]
        safe = sanitize(name)
        fname = f"{sid}_{safe}.pdf"
        fpath = OUTPUT / fname
        if fpath.exists() and fpath.stat().st_size > 1000:
            skipped += 1
            if idx % 50 == 0:
                print(f"[{idx+1}/{total}] SKIP {sid} exists", flush=True)
            continue

        print(f"\n[{idx+1}/{total}] {sid} {name}", flush=True)
        for attempt in range(3):
            try:
                html = page.evaluate("""async (sid) => {
                    const r = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                        method:'POST',
                        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                        body:`rootData=${sid}&flagreq=transactionCheck`
                    });
                    return await r.text();
                }""", sid)

                if "EMS Login" in html or "<title>EMS Login</title>" in html:
                    print(f"  Session expired, re-login attempt {attempt+1}", flush=True)
                    if not login(page):
                        time.sleep(2)
                        continue
                    continue

                if "No transaction found" in html:
                    print(f"  No transaction found", flush=True)
                    no_data += 1
                    with open(LOG, "a", encoding="utf-8") as lf:
                        lf.write(f"{sid},{name},No transaction,SKIP\n")
                    break

                if "<table" not in html:
                    snippet = html[:400].replace("\n"," ")
                    print(f"  No table, snippet: {snippet[:200]}", flush=True)
                    if "Error" in html or "not found" in html.lower():
                        print(f"  Class roll not found", flush=True)
                        no_data += 1
                        with open(LOG, "a", encoding="utf-8") as lf:
                            lf.write(f"{sid},{name},Not found,SKIP\n")
                        break
                    if attempt <2:
                        time.sleep(1)
                        continue
                    failed+=1
                    break

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("tbody tr")
                if not rows:
                    print(f"  No rows", flush=True)
                    no_data+=1
                    break
                parsed=[]
                for tr in rows:
                    tds=tr.find_all("td")
                    if len(tds)<7: continue
                    sname=tds[0].get_text(strip=True)
                    dstr=tds[3].get_text(strip=True)
                    btn=tds[6].find("button")
                    onclick=btn.get("onclick") if btn else ""
                    m=re.search(r"printReceipts\((\d+)\)", onclick or "")
                    pid=m.group(1) if m else None
                    fee=tds[4].get_text(strip=True)
                    try:
                        dobj=parse_date(dstr)
                    except:
                        continue
                    if pid:
                        parsed.append({"sname":sname,"dstr":dstr,"dobj":dobj,"pid":pid,"fee":fee})
                if not parsed:
                    print(f"  No parsable", flush=True)
                    no_data+=1
                    break
                norm = lambda s: " ".join(s.split()).lower()
                cand = [x for x in parsed if norm(x["sname"])==norm(name)]
                if not cand:
                    print(f"  Warning no matching name, using all. Expected '{name}', got {[x['sname'] for x in parsed[:2]]}", flush=True)
                    cand = parsed
                latest = max(cand, key=lambda x: x["dobj"])
                print(f"  Found {len(parsed)} rows, latest {latest['dstr']} {latest['fee']} pid {latest['pid']}", flush=True)

                enc = page.evaluate("""async (pid) => {
                    const r = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                        method:'POST',
                        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                        body:`rootData=${pid}&flagreq=ajaxEncryption`
                    });
                    return (await r.text()).trim();
                }""", latest["pid"])
                if not enc or "Error" in enc or len(enc)<10:
                    print(f"  Enc failed: {enc[:200]}", flush=True)
                    if attempt<2:
                        time.sleep(1)
                        continue
                    failed+=1
                    break
                print(f"  Enc {enc[:30]}...", flush=True)

                # Fetch PDF via page.evaluate as base64 (avoid context.request socket hang up)
                b64 = page.evaluate("""async (code) => {
                    const r = await fetch(`https://bgc.eshiksabd.com/std_coll_slip.php?xxCode=${code}`);
                    const buf = await r.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let binary = '';
                    // Chunk to avoid call stack overflow for large binary
                    const chunkSize = 0x8000;
                    for (let i=0; i<bytes.length; i+=chunkSize) {
                        binary += String.fromCharCode.apply(null, bytes.subarray(i, i+chunkSize));
                    }
                    return btoa(binary);
                }""", enc)

                if not b64 or len(b64) < 1000:
                    print(f"  b64 failed len {len(b64) if b64 else 0}", flush=True)
                    if attempt<2:
                        time.sleep(1)
                        continue
                    failed+=1
                    break
                # Decode
                try:
                    pdf_bytes = base64.b64decode(b64)
                except Exception as e:
                    print(f"  base64 decode failed: {e}", flush=True)
                    failed+=1
                    break
                if b"%PDF" not in pdf_bytes[:20]:
                    print(f"  Not PDF after decode, first 20: {pdf_bytes[:20]}", flush=True)
                    # Try fallback: maybe need to handle \r\n prefix as earlier
                    if b"%PDF" not in pdf_bytes:
                        if attempt<2:
                            time.sleep(1)
                            continue
                        failed+=1
                        break
                with open(fpath, "wb") as f:
                    f.write(pdf_bytes)
                print(f"  ✓ Saved {fname} ({len(pdf_bytes)} bytes)", flush=True)
                success+=1
                with open(LOG, "a", encoding="utf-8") as lf:
                    lf.write(f"{sid},{name},{latest['dstr']},{latest['fee']},{latest['pid']},{fname},OK\n")
                time.sleep(0.7)
                break

            except Exception as e:
                print(f"  Exception attempt {attempt+1}: {e}", flush=True)
                traceback.print_exc()
                if attempt<2:
                    time.sleep(1.5)
                    # Re-login check
                    try:
                        if "Student Information Center" not in page.title():
                            login(page)
                    except:
                        pass
                    continue
                else:
                    failed+=1
                    with open(LOG, "a", encoding="utf-8") as lf:
                        lf.write(f"{sid},{name},EXCEPTION,{e},FAIL\n")
                    break
        if (idx+1) % 20 == 0:
            print(f"\n--- Progress {idx+1}/{total} success={success} skipped={skipped} failed={failed} no_data={no_data} ---", flush=True)
        time.sleep(0.3)

    browser.close()
    print(f"\nDone. Total {total} Success {success} Skipped {skipped} Failed {failed} NoData {no_data}", flush=True)
    print(f"Output contains {len(list(OUTPUT.glob('*.pdf')))} files", flush=True)
    with open(LOG, "a") as lf:
        lf.write(f"FINAL {total} {success} {skipped} {failed} {no_data}\n")
