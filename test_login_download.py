#!/usr/bin/env python3
from playwright.sync_api import sync_playwright
import time, re, json, pathlib
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://bgc.eshiksabd.com"
OUTPUT = pathlib.Path("/Users/th28/BGC/Student receipt")
OUTPUT.mkdir(parents=True, exist_ok=True)

students = json.load(open("/Users/th28/BGC/students.json"))
# Take first 5 that are not yet downloaded? We'll do 0006 onwards for test
# But for verification, redo 0001-0005 with overwrite=False
test_ids = students[:5]

def sanitize(n):
    return " ".join(n.split()).replace("/","_").replace("\\","_").replace(":","_").replace("*","_").replace("?","_").replace('"',"_").replace("<","_").replace(">","_").replace("|","_")

def parse_date(s):
    months = {"Jan":0,"Feb":1,"Mar":2,"Apr":3,"May":4,"Jun":5,"Jul":6,"Aug":7,"Sep":8,"Oct":9,"Nov":10,"Dec":11}
    p=s.split("-")
    return datetime(int(p[2]), months[p[1]], int(p[0]))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    print("Goto login page")
    page.goto(f"{BASE}/main", wait_until="networkidle")
    time.sleep(1)
    print(f"Login page title: {page.title()}, url: {page.url}")
    # Fill login
    page.get_by_role("textbox", name="User ID").fill("bgcstudent")
    page.get_by_role("textbox", name="Password").fill("bgcstudent")
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    print(f"After login title: {page.title()}, url: {page.url}")
    if "Student Information Center" not in page.title():
        print("Login failed, content snippet:", page.content()[:500])
        browser.close()
        exit(1)
    print("Login successful")
    # Ensure we are on Result-Enquiry-Center
    if "Result-Enquiry-Center" not in page.url:
        page.goto(f"{BASE}/Result-Enquiry-Center", wait_until="networkidle")
        time.sleep(1)
        print(f"Goto Result-Enquiry-Center: {page.title()}, {page.url}")

    # Now loop
    for entry in test_ids:
        sid = entry["id"]
        name = entry["name"]
        safe = sanitize(name)
        fname = f"{sid}_{safe}.pdf"
        fpath = OUTPUT / fname
        print(f"\n=== {sid} {name} ===")
        if fpath.exists():
            print(f"  Exists, skipping (size {fpath.stat().st_size})")
            continue
        # Use page.evaluate to do transactionCheck
        html = page.evaluate("""async (sid) => {
            const r = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                method:'POST',
                headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                body:`rootData=${sid}&flagreq=transactionCheck`
            });
            return await r.text();
        }""", sid)
        if "<table" not in html:
            print(f"  No table, html snippet: {html[:300]}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("tbody tr")
        print(f"  Found {len(rows)} rows")
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
                print(f"    {dstr} {pid} {sname} {fee}")
        if not parsed:
            print("  No parsable")
            continue
        # Filter matching
        norm = lambda s: " ".join(s.split()).lower()
        cand = [x for x in parsed if norm(x["sname"])==norm(name)]
        if cand:
            print(f"  Filtered {len(cand)} matching")
        else:
            cand=parsed
            print(f"  No matching, using all {len(parsed)}")
        latest = max(cand, key=lambda x: x["dobj"])
        print(f"  Latest: {latest['dstr']} pid {latest['pid']}")
        # encryption
        enc = page.evaluate("""async (pid) => {
            const r = await fetch('https://bgc.eshiksabd.com/controller_student_module.php', {
                method:'POST',
                headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
                body:`rootData=${pid}&flagreq=ajaxEncryption`
            });
            return (await r.text()).trim();
        }""", latest["pid"])
        print(f"  Enc: {enc}")
        if not enc or "Error" in enc:
            print("  enc failed")
            continue
        pdf_url = f"{BASE}/std_coll_slip.php?xxCode={enc}"
        print(f"  GET {pdf_url}")
        resp = context.request.get(pdf_url, headers={"Referer": f"{BASE}/Result-Enquiry-Center"})
        print(f"  PDF status {resp.status}, ct {resp.headers.get('content-type')}")
        if resp.status != 200:
            print(resp.text()[:500])
            continue
        body = resp.body()
        print(f"  PDF len {len(body)}, header {body[:10]}")
        if not body.startswith(b"%PDF") and b"%PDF" not in body[:20]:
            print("  Not PDF")
            continue
        with open(fpath, "wb") as f:
            f.write(body)
        print(f"  Saved {fpath}")
        time.sleep(1)
    browser.close()
    print("Done")
