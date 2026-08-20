from django.urls import path
from . import views

urlpatterns = [
    path('', views.scraper_home, name='scraper-home'),
    path('search/profile/', views.search_profile, name='search-profile'),
    path('search/domain/', views.search_domain, name='search-domain'),
    path('analyze/', views.analyze_profile, name='analyze-profile'),
    path('pitch/', views.generate_pitch, name='generate-pitch'),
    path('save/', views.save_to_contacts, name='save-contacts'),
    path('update/', views.update_contact, name='update-contact'),
    path('delete/', views.delete_contact, name='delete-contact'),
    path('list/', views.get_all_contacts, name='get-all-contacts'),
    path('download-csv/', views.download_csv, name='download-csv'),
    path('check-api-status/', views.check_api_status, name='check-api-status'),

    # --- Scheduled Scraper (daily keyword scraping) ---
    path('keywords/', views.scrape_keywords_list, name='scrape-keywords-list'),
    path('keywords/add/', views.scrape_keyword_add, name='scrape-keyword-add'),
    path('keywords/toggle/', views.scrape_keyword_toggle, name='scrape-keyword-toggle'),
    path('keywords/delete/', views.scrape_keyword_delete, name='scrape-keyword-delete'),
    path('runs/', views.scrape_runs_list, name='scrape-runs-list'),
    path('runs/detail/', views.scrape_run_detail, name='scrape-run-detail'),
    path('run-now/', views.run_scrape_now, name='run-scrape-now'),
    path('scheduler/run/', views.scheduler_run, name='scheduler-run'),
    path('progress/', views.scrape_progress, name='scrape-progress'),
    path('stats/', views.scrape_stats, name='scrape-stats'),
]
