from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
    page = context.new_page()
    for url in ["https://bgc.eshiksabd.com/main", "https://bgc.eshiksabd.com/Result-Enquiry-Center"]:
        print(f"Goto {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(1)
        print(f"  Title: {page.title()}, URL: {page.url}")
        print(f"  Content snippet: {page.content()[:500][:200]}")
        time.sleep(1)
    # Try again
    page.goto("https://bgc.eshiksabd.com/Result-Enquiry-Center", wait_until="networkidle")
    time.sleep(1)
    print(f"Second try Title: {page.title()}, URL: {page.url}")
    print("Cookies:", context.cookies())
    browser.close()
