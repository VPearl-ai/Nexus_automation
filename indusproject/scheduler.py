# indus_scraper/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from .scrapper import scrape_indus_po_data

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(scrape_indus_po_data, 'interval', minutes=2)
    scheduler.start()
    print("[Scheduler] Scraper will run every 10 seconds.")
