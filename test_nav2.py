from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
        viewport={"width":1280, "height":800},
        locale="en-US"
    )
    page = context.new_page()
    # Hide webdriver
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    for url in ["https://bgc.eshiksabd.com/Result-Enquiry-Center"]:
        print(f"Goto {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        print(f"  Title: {page.title()}, URL: {page.url}")
        # Check for Student Information Center text
        content = page.content()
        if "Student Information Center" in content:
            print("  Found Student Information Center in content")
        else:
            print("  NOT found, content start", content[:400])
        time.sleep(1)
    # Try via fetch inside page
    print("Trying fetch via page.evaluate")
    html = page.evaluate("() => fetch('https://bgc.eshiksabd.com/controller_student_module.php', {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}, body:'rootData=1202425010001&flagreq=transactionCheck'}).then(r=>r.text()).then(t=>t.slice(0,500))")
    print(f"Fetch result snippet: {html[:500]}")
    browser.close()
