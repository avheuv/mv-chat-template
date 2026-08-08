from playwright.sync_api import sync_playwright

def run_cuj(page):
    page.goto("http://localhost:5173/?prototype=meryl")
    page.wait_for_timeout(1500)

    page.get_by_role("combobox").select_option(label="Quadratic Equations")
    page.wait_for_timeout(500)

    page.get_by_role("button", name="Start").click()
    page.wait_for_timeout(2000)

    page.screenshot(path="/home/jules/verification/screenshots/verification2.png")
    page.wait_for_timeout(1000)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        run_cuj(page)
        context.close()
        browser.close()
