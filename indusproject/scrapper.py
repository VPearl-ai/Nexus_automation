import os, json, datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError
from redis import Redis

load_dotenv()

# ================= REDIS HELPERS =================
def ConnectRedis():
    try:
        return Redis(
            host=os.getenv("REDIS_HOST"),
            port=int(os.getenv("REDIS_PORT")),
            db=int(os.getenv("REDIS_DB"))
        )
    except Exception as e:
        print("Error in connecting redis:", str(e))
        return None

def get_redis_data(key):
    try:
        redis_client = ConnectRedis()
        cached_data = redis_client.get(key)
        return json.loads(cached_data) if cached_data else []
    except Exception as e:
        print(f"[CACHE ERROR] {e}")
        return []

def set_redis_data(key, data):
    try:
        redis_client = ConnectRedis()
        redis_client.set(key, json.dumps(data))
    except Exception as e:
        print(f"[REDIS SET ERROR] {e}")

def remove_duplicates_by_date(existing_data, new_data):
    try:
        existing_dates = {
            item.get("order_date") or item.get("creation_date")
            for item in existing_data
            if item.get("order_date") or item.get("creation_date")
        }

        unique_new_data = [
            item for item in new_data
            if (item.get("order_date") or item.get("creation_date")) not in existing_dates
        ]

        return unique_new_data
    except Exception as e:
        print(f"[DEDUPE ERROR] {e}")
        return new_data

def store_po_data_with_deduplication(new_data):
    try:
        existing_po_data = get_redis_data("indus_po_data")
        filtered_new_data = remove_duplicates_by_date(existing_po_data, new_data)

        set_redis_data("indus_latest_data", filtered_new_data)
        print(f"[✓] Stored {len(filtered_new_data)} new PO records to 'indus_latest_data'")

        updated_po_data = existing_po_data + filtered_new_data
        set_redis_data("indus_po_data", updated_po_data)
        print(f"[✓] Updated 'indus_po_data' with total {len(updated_po_data)} records")

        return filtered_new_data
    except Exception as e:
        print(f"[STORE ERROR] {e}")
        return []

# ================= DATA GROUPING =================
def group_items_by_indus_id(items):
    try:
        grouped = {}
        for item in items:
            site_id = item.get('indus_id', '').strip()
            project_id = item.get('project_id', '').strip()
            if not site_id:
                continue
            key = (site_id, project_id)
            if key not in grouped:
                grouped[key] = {
                    "site_id": site_id,
                    "project_id": project_id,
                    "line_items": []
                }
            grouped[key]["line_items"].append({
                "description": item.get('description', ''),
                "item_job": item.get('item_job', ''),
                "line": item.get('line', ''),
                "price": item.get('price', ''),
                "qty": item.get('qty', '')
            })
        return list(grouped.values())
    except Exception as e:
        print(f"[ERROR] Error grouping items by indus_id: {e}")
        return []

# ================= SCRAPING HELPERS =================
def scrape_po_details(page, po_number):
    try:
        page.wait_for_selector("tbody tr", timeout=60000)  # ⬅ longer timeout
        items, column_mapping = [], {}
        rows = page.query_selector_all("tbody tr")

        # Build column map
        for row in rows:
            headers = row.query_selector_all("th")
            if headers:
                for idx, header in enumerate(headers):
                    column_mapping[header.inner_text().strip()] = idx
                break

        if not column_mapping:
            headers = page.query_selector_all("thead th, table th")
            for idx, header in enumerate(headers):
                column_mapping[header.inner_text().strip()] = idx

        # Parse rows
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 10:
                continue
            try:
                line = cells[column_mapping.get("Line", 2)].inner_text().strip()
                if not line or not line.isdigit():
                    continue
                item_job = cells[column_mapping.get("Item/Job", 4)].inner_text().strip()
                description = cells[column_mapping.get("Description", 6)].inner_text().strip()
                qty = cells[column_mapping.get("Qty", 8)].inner_text().strip()
                price = cells[column_mapping.get("Price", 9)].inner_text().strip()
                indus_id = cells[column_mapping.get("Site ID", 25)].inner_text().strip() if 25 < len(cells) else ''
                project_id = cells[column_mapping.get("Project Name", 27)].inner_text().strip() if 27 < len(cells) else ''
                items.append({
                    "line": line,
                    "item_job": item_job,
                    "description": description,
                    "qty": qty,
                    "price": price,
                    "project_id": project_id,
                    "indus_id": indus_id
                })
            except Exception as e:
                print(f"[WARNING] Error parsing row in PO {po_number}: {e}")
        return items
    except TimeoutError:
        print(f"[TIMEOUT] Table not loaded for PO {po_number}")
        return []
    except Exception as e:
        print(f"[ERROR] Failed to scrape PO {po_number}: {e}")
        return []


# ================= PHASE 1: COLLECT PO NUMBERS =================
def collect_non_zero_po_numbers(page):
    po_list = []


    page.wait_for_selector("span#ResultRN1 table tbody tr", timeout=30000)
    rows = page.query_selector_all("span#ResultRN1 table tbody tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) >= 6:
            po_number = cells[0].inner_text().strip()
            rev = cells[1].inner_text().strip()
            order_date = cells[5].inner_text().strip()
            if po_number and rev and rev != "0":
                po_list.append({
                        "po_number": po_number,
                        "rev": rev,
                        "order_date": order_date,
                        "scraped_at": datetime.datetime.now().isoformat(),
                        "items": []
                })
        # Next page
        """        next_button = page.query_selector("a:has-text('Next')")
        if next_button:
            class_attr = next_button.get_attribute("class") or ""
            if "disabled" not in class_attr.lower():
                page.click("a:has-text('Next')")
                page.wait_for_load_state("networkidle", timeout=30000)
                page_number += 1
                continue
        break"""
    return po_list

def collect_rev0_po_numbers(page):
    po_list = []
    page.wait_for_selector("a#POS_PO_HISTORY", timeout=15000)
    page.click("a#POS_PO_HISTORY")
    page.wait_for_selector("button[title='Advanced Search']", timeout=30000)
    page.click("button[title='Advanced Search']")
    page.wait_for_selector("button#customizeSubmitButton", timeout=30000)
    page.click("button#customizeSubmitButton")
    page.wait_for_load_state('load')
    page.wait_for_timeout(5000)

    #page_number = 1
    #while page_number <= max_pages:
    rows = page.query_selector_all("table#PosRevHistoryTable\\:Content tbody tr")
    for row in rows:
        po_number_elem = row.query_selector("td a[id*='PosPoNumRelNum']")
        po_number = po_number_elem.inner_text().strip() if po_number_elem else ""
        creation_date_elem = row.query_selector("td span[id*='PosOrderDateTime']")
        creation_date = creation_date_elem.inner_text().strip() if creation_date_elem else ""
        if po_number:
            po_list.append({
                    "po_number": po_number,
                    "rev": "0",
                    "creation_date": creation_date,
                    "scraped_at": datetime.datetime.now().isoformat(),
                    "items": []
            })
        # Next page
        """        next_button = page.query_selector("a:has-text('Next')")
        if next_button:
            class_attr = next_button.get_attribute("class") or ""
            if "disabled" not in class_attr.lower():
                page.click("a:has-text('Next')")
                page.wait_for_load_state("networkidle", timeout=30000)
                page_number += 1
                continue
        break"""
    return po_list

# ================= PAGINATION HELPER =================
"""def go_to_first_page(page):
    while True:
        prev_button = page.query_selector("a:has-text('Previous')")
        if prev_button:
            class_attr = prev_button.get_attribute("class") or ""
            if "disabled" not in class_attr.lower():
                prev_button.click()
                page.wait_for_load_state("networkidle", timeout=30000)
                continue
        break"""

# ================= MAIN SCRAPER =================
def scrape_indus_po_data():
    result = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(os.getenv("ERP_LOGIN_URL"))

            # Login
            page.wait_for_selector("input#usernameField", timeout=30000)
            page.fill("input#usernameField", os.getenv("ERP_USERNAME"))
            page.fill("input#passwordField", os.getenv("ERP_PASSWORD"))
            page.click("button:has-text('Log In')")
            page.wait_for_load_state("networkidle", timeout=30000)

            # ========= STEP 1: Non-zero rev POs =========
            print("[INFO] Collecting non-zero rev PO numbers...")
            page.wait_for_selector("img[title='Expand']", timeout=30000)
            page.click("img[title='Expand']")
            page.wait_for_selector("li >> text=Home Page", timeout=30000)
            page.click("li >> text=Home Page")
            page.wait_for_selector("a:has-text('Orders')", timeout=30000)
            page.click("a:has-text('Orders')")
            non_zero_pos = collect_non_zero_po_numbers(page)
            #go_to_first_page(page)

            print(f"[INFO] Scraping details for {len(non_zero_pos)} non-zero rev POs...")
            for po in non_zero_pos:
                po_link_selector = f"a:has-text('{po['po_number']}')"
                try:
                    page.wait_for_selector(po_link_selector, timeout=30000)
                    page.click(po_link_selector)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    items = scrape_po_details(page, po['po_number'])
                    po['project'] = group_items_by_indus_id(items)
                    del po['items']
                    page.go_back()
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception as e:
                    print(f"[WARNING] Could not scrape details for PO {po['po_number']}: {e}")
                    continue
                result.append(po)

            # ========= STEP 2: Rev=0 POs =========
            print("[INFO] Collecting rev=0 PO numbers...")
            rev0_pos = collect_rev0_po_numbers(page)
            #go_to_first_page(page)

            print(f"[INFO] Scraping details for {len(rev0_pos)} rev=0 POs...")
            for po in rev0_pos:
                po_link_selector = f"a[id*='PosPoNumRelNum'][title='{po['po_number']}']"
                try:
                    page.wait_for_selector(po_link_selector, timeout=30000)
                    page.click(po_link_selector)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    items = scrape_po_details(page, po['po_number'])
                    po['project'] = group_items_by_indus_id(items)
                    del po['items']
                    page.go_back()
                    page.wait_for_load_state("networkidle", timeout=30000)
                except Exception as e:
                    print(f"[WARNING] Could not scrape rev=0 PO {po['po_number']}: {e}")
                    continue
                result.append(po)

            browser.close()
            return store_po_data_with_deduplication(result)

    except Exception as e:
        print(f"[SCRAPER ERROR] {e}")
        return store_po_data_with_deduplication(result) if result else []

