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
]
