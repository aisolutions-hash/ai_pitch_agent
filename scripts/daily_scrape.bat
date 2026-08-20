@echo off
REM ============================================================
REM  Sales Agent - Daily LinkedIn Keyword Scrape (local cron)
REM  Runs the Django management command and appends output to
REM  logs\scraper_cron.log
REM
REM  Registered in Windows Task Scheduler as:
REM    "SalesAgentDailyLinkedInScrape" (daily)
REM
REM  Manual usage:
REM    scripts\daily_scrape.bat              (real run)
REM    scripts\daily_scrape.bat --dry-run    (test, no API calls)
REM ============================================================

cd /d C:\Sales_agent

if not exist logs mkdir logs

echo ================================================== >> logs\scraper_cron.log
echo [%DATE% %TIME%] Starting daily keyword scrape >> logs\scraper_cron.log

python manage.py daily_keyword_scrape %* >> logs\scraper_cron.log 2>&1

echo [%DATE% %TIME%] Finished with exit code %ERRORLEVEL% >> logs\scraper_cron.log
