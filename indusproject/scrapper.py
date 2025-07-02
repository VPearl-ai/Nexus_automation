import os, json, datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright,TimeoutError
from redis import Redis

# Load environment variables
load_dotenv()

print(os.getenv("ERP_USERNAME"))
print(os.getenv("ERP_PASSWORD"))

# Redis connection
redis_client = Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    db=int(os.getenv("REDIS_DB"))
)

from playwright.sync_api import sync_playwright, TimeoutError

def scrape_indus_po_data():
    result = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # Set to False for debugging
            context = browser.new_context()
            page = context.new_page()

            page.goto(os.getenv("ERP_LOGIN_URL"))

            # Wait and fill login form using actual input selectors
            page.wait_for_selector("input#usernameField", timeout=15000)  # example ID
            page.fill("input#usernameField", os.getenv("ERP_USERNAME"))
            page.fill("input#passwordField", os.getenv("ERP_PASSWORD"))
            page.click("button:has-text('Log In')")  # use the visible button text

            page.wait_for_load_state("networkidle", timeout=20000)

            # Expand the India Local iSupplier section by clicking the "Expand" image
            page.wait_for_selector("img[title='Expand']", timeout=10000)
            page.click("img[title='Expand']")

            # 🔁 INSTEAD OF WAITING FOR ul, wait for the specific <li>
            page.wait_for_selector("li >> text=Home Page", timeout=15000)
            page.click("li >> text=Home Page")

            page.wait_for_selector("a:has-text('Orders')", timeout=15000)
            page.click("a:has-text('Orders')")

            # Wait for Orders page to load
            page.wait_for_selector("span#ResultRN1", timeout=20000)

            # Extract table rows
            rows = page.query_selector_all("span#ResultRN1 table tbody tr")
            for row in rows:
                cells = row.query_selector_all("td")

                # Skip rows with not enough columns or junk pagination controls
                if len(cells) >= 6:
                    po_text = cells[0].inner_text().strip()
                    if "Previous" in po_text or "Next" in po_text or not po_text:
                        continue  # Skip pagination or empty rows

                    result.append({
                        "po_number": po_text,
                        "rev": cells[1].inner_text().strip(),
                        "order_date": cells[5].inner_text().strip(),
                        "scraped_at": datetime.datetime.now().isoformat()
                    })

            redis_client.set("indus_po_data", json.dumps(result), ex=120)
            print(f"[✓] Scraped {len(result)} PO records.")
            browser.close()

    except TimeoutError as e:
        print(f"[SCRAPER TIMEOUT] {e}")
    except Exception as e:
        print(f"[SCRAPER ERROR] {e}")