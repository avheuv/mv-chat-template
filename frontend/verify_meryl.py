from playwright.sync_api import sync_playwright

def run_cuj(page):
    page.goto("http://localhost:5173/?prototype=meryl")
    page.wait_for_timeout(1500)

    # Enter details on splash screen (use placeholder text as locator if label is hard)
    page.get_by_placeholder("Enter student ID").fill("jules123")
    page.wait_for_timeout(500)
    page.get_by_role("combobox").select_option(label="Quadratic Equations")
    page.wait_for_timeout(500)

    # Click open
    page.get_by_role("button", name="Start").click()
    page.wait_for_timeout(2000)

    # Take screenshot of the initial chat state with the Meryl dock
    page.screenshot(path="/home/jules/verification/screenshots/verification.png")
    page.wait_for_timeout(2000)

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir="/home/jules/verification/videos"
        )
        page = context.new_page()
        try:
            run_cuj(page)
        finally:
            context.close()
            browser.close()
