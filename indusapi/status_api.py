import os
import asyncio
from playwright.async_api import async_playwright
from loguru import logger


logger.add("logs/app.log", rotation="5 MB", retention="7 days", level="INFO")

# Configuration for scraper
class ScraperConfig:
    email = os.getenv("ERP_EMAIL", "bharathielectricalanna@gmail.com")
    password = os.getenv("ERP_PASSWORD", "Shyam.erp@#1234")
    base_url = "https://induserp.industowers.com/OA_HTML/AppsLocalLogin.jsp"
    max_pages = 5
    page_load_timeout = 15000
    navigation_timeout = 20000
    sleep_interval = 5.0

class POScraper:
    def __init__(self, config):
        self.config = config
        self.records = []

    async def _login(self, page):
        logger.info("Logging in to ERP system...")
        try:
            await page.goto(self.config.base_url)
            await asyncio.sleep(self.config.sleep_interval)
            
            await page.fill('input[name="usernameField"]', self.config.email)
            await page.fill('input[name="passwordField"]', self.config.password)
            await page.press('input[name="passwordField"]', 'Enter')
            await asyncio.sleep(self.config.sleep_interval)
        except Exception as e:
            logger.error(f"Login failed: {e}")
            raise

    async def _navigate_to_orders(self, page):
        logger.info("Navigating to Orders section...")
        try:
            await page.click("img[title='Expand']")
            await page.wait_for_selector("li >> text=Home Page", timeout=self.config.page_load_timeout)
            await page.click("li >> text=Home Page")
            await page.wait_for_selector("a:has-text('Orders')", timeout=self.config.page_load_timeout)
            await page.click("a:has-text('Orders')")
            await page.wait_for_selector("span#ResultRN1", timeout=self.config.navigation_timeout)
        except Exception as e:
            logger.error(f"Navigation to Orders failed: {e}")
            raise

    async def _scrape_page(self, page):
        try:
            await page.wait_for_selector("span#ResultRN1 table tbody tr", timeout=self.config.page_load_timeout)
            rows = await page.query_selector_all("span#ResultRN1 table tbody tr")
            
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 13:
                    po_text = (await cells[0].inner_text()).strip()
                    if po_text and "Previous" not in po_text and "Next" not in po_text:
                        self.records.append({
                            "po_number": po_text,
                            "status": (await cells[12].inner_text()).strip()
                        })
        except Exception as e:
            logger.error(f"Error scraping page: {e}")
            raise

    async def scrape_data(self):
        try:
            async with async_playwright() as p:
                logger.info("Launching browser...")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                await self._login(page)
                await self._navigate_to_orders(page)

                page_count = 0
                while page_count < self.config.max_pages:
                    logger.info(f"Scraping page {page_count + 1}...")
                    await self._scrape_page(page)
                    page_count += 1
                    logger.info(f"Total records scraped so far: {len(self.records)}")

                    if page_count >= self.config.max_pages:
                        logger.info("Reached max pages. Stopping pagination.")
                        break

                    try:
                        next_button = await page.query_selector("a:has-text('Next')")
                        if next_button:
                            class_attr = await next_button.get_attribute("class") or ""
                            if "disabled" not in class_attr.lower():
                                logger.info("Clicking 'Next' to load more records...")
                                await next_button.click()
                                await asyncio.sleep(self.config.sleep_interval)
                            else:
                                logger.info("Next button is disabled. No more pages.")
                                break
                        else:
                            logger.info("No 'Next' button found. Ending pagination.")
                            break
                    except Exception as e:
                        logger.warning(f"Error during pagination: {e}")
                        break

                await browser.close()
                logger.info(f"Scraping completed. Total records: {len(self.records)}")
                return {"status": "success", "records": self.records}

        except Exception as e:
            logger.exception("Scraping failed")
            return {"status": "error", "message": str(e)}

def scrape_po_status():
    try:
        config = ScraperConfig()
        scraper = POScraper(config)
        return asyncio.run(scraper.scrape_data())
    except Exception as e:
        logger.exception("Error in scrape_po_status")
        return {"status": "error", "message": str(e)}