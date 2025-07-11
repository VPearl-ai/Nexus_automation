import os, json, datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError
from redis import Redis
load_dotenv()

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

def remove_duplicates_by_order_date(existing_data, new_data):
    try:
        existing_dates = {item.get('order_date') for item in existing_data}
        unique_new_data = [item for item in new_data if item.get('order_date') not in existing_dates]
        return unique_new_data
    except Exception as e:
        print(f"[DEDUPE ERROR] {e}")
        return new_data

def store_po_data_with_deduplication(new_data):
    try:
        existing_po_data = get_redis_data("indus_po_data")
        filtered_new_data = remove_duplicates_by_order_date(existing_po_data, new_data)

        # Replace indus_latest_data with only new ones
        set_redis_data("indus_latest_data", filtered_new_data)
        print(f"[✓] Stored {len(filtered_new_data)} new PO records to 'indus_latest_data'")

        # Append to indus_po_data
        updated_po_data = existing_po_data + filtered_new_data
        set_redis_data("indus_po_data", updated_po_data)
        print(f"[✓] Updated 'indus_po_data' with total {len(updated_po_data)} records")

        return filtered_new_data
    except Exception as e:
        print(f"[STORE ERROR] {e}")
        return []


def group_items_by_indus_id(items):
    try:
        grouped_projects = {}
        for item in items:
            indus_id = item.get('indus_id', '').strip()
            if not indus_id:
                continue
            item_data = {
                "project_id": item.get('project_id', ''),
                "description": item.get('description', ''),
                "item_job": item.get('item_job', ''),
                "line": item.get('line', ''),
                "price": item.get('price', ''),
                "qty": item.get('qty', '')
            }
            grouped_projects.setdefault(indus_id, []).append(item_data)
        return grouped_projects
    except Exception as e:
        print(f"[ERROR] Error grouping items by indus_id: {e}")
        return {}

def scrape_po_details(page, po_number):
    try:
        page.wait_for_selector("tbody tr", timeout=30000)
        items = []
        rows = page.query_selector_all("tbody tr")
        column_mapping = {}

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

        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 10:
                continue
            try:
                line = cells[column_mapping.get("Line", 2)].inner_text().strip()
                if not line or line == "Line" or not line.isdigit():
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
    except Exception as e:
        print(f"[ERROR] Failed to scrape PO {po_number}: {e}")
        return []

def scrape_indus_po_data():
    result = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(os.getenv("ERP_LOGIN_URL"))

            page.wait_for_selector("input#usernameField", timeout=30000)
            page.fill("input#usernameField", os.getenv("ERP_USERNAME"))
            page.fill("input#passwordField", os.getenv("ERP_PASSWORD"))
            page.click("button:has-text('Log In')")
            page.wait_for_load_state("networkidle", timeout=30000)

            # ===== Expand menu with retry logic =====
            try:
                page.wait_for_selector("img[title='Expand']", timeout=30000)
                page.click("img[title='Expand']")
            except TimeoutError:
                print("[WARNING] 'Expand' button not found. Retrying after page reload...")
                page.reload()
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_selector("img[title='Expand']", timeout=30000)
                page.click("img[title='Expand']")

            # ===== Home Page navigation =====
            page.wait_for_selector("li >> text=Home Page", timeout=30000)
            page.click("li >> text=Home Page")

            # ===== Orders Page =====
            page.wait_for_selector("a:has-text('Orders')", timeout=30000)
            page.click("a:has-text('Orders')")
            page.wait_for_selector("span#ResultRN1", timeout=30000)

            rows = page.query_selector_all("span#ResultRN1 table tbody tr")
            po_list = []

            for row in rows:
                cells = row.query_selector_all("td")
                if len(cells) >= 6:
                    po_text = cells[0].inner_text().strip()
                    if "Previous" in po_text or "Next" in po_text or not po_text:
                        continue
                    po_data = {
                        "po_number": po_text,
                        "rev": cells[1].inner_text().strip(),
                        "order_date": cells[5].inner_text().strip(),
                        "scraped_at": datetime.datetime.now().isoformat(),
                        "items": []
                    }
                    po_list.append(po_data)

            print(f"[INFO] Found {len(po_list)} PO records to process")

            for i, po_data in enumerate(po_list):
                try:
                    if i > 0:
                        try:
                            page.click("a:has-text('Orders')")
                            page.wait_for_selector("span#ResultRN1", timeout=20000)
                        except TimeoutError:
                            print("[WARNING] Orders page didn't load. Retrying after refresh...")
                            page.reload()
                            page.wait_for_selector("a:has-text('Orders')", timeout=30000)
                            page.click("a:has-text('Orders')")
                            page.wait_for_selector("span#ResultRN1", timeout=30000)

                    po_link_selector = f"a:has-text('{po_data['po_number']}')"
                    try:
                        page.wait_for_selector(po_link_selector, timeout=10000)
                        page.click(po_link_selector)
                        page.wait_for_load_state("networkidle", timeout=15000)
                        items = scrape_po_details(page, po_data['po_number'])
                        grouped_projects = group_items_by_indus_id(items)
                        po_data['project'] = grouped_projects
                        del po_data['items']
                    except TimeoutError:
                        print(f"[WARNING] Timeout scraping PO {po_data['po_number']}. Retrying after refresh...")
                        # Retry after refresh
                        page.reload()
                        page.wait_for_selector("a:has-text('Orders')", timeout=30000)
                        page.click("a:has-text('Orders')")
                        page.wait_for_selector("span#ResultRN1", timeout=30000)
                        try:
                            page.wait_for_selector(po_link_selector, timeout=10000)
                            page.click(po_link_selector)
                            page.wait_for_load_state("networkidle", timeout=15000)
                            items = scrape_po_details(page, po_data['po_number'])
                            grouped_projects = group_items_by_indus_id(items)
                            po_data['project'] = grouped_projects
                            del po_data['items']
                        except Exception as retry_err:
                            print(f"[ERROR] Failed on retry for PO {po_data['po_number']}: {retry_err}")
                            continue

                    result.append(po_data)
                except Exception as e:
                    print(f"[ERROR] Error processing PO {po_data['po_number']}: {e}")
                    continue

            browser.close()
            return store_po_data_with_deduplication(result)

    except TimeoutError as e:
        print(f"[SCRAPER TIMEOUT] {e}")
        return store_po_data_with_deduplication(result) if result else []
    except Exception as e:
        print(f"[SCRAPER ERROR] {e}")
        return store_po_data_with_deduplication(result) if result else []
