# extractor/urls.py

from django.urls import path
from . import views

# --- FIX: Define the app_name namespace ---
app_name = 'extractor'
# ------------------------------------------

urlpatterns = [
    # Main search view
    path('', views.search_view, name='search'), # Updated name from 'search_view' to 'search' for consistency
    
    # Download CSV
    path('download_csv/', views.download_csv, name='download_csv'),
    
    # Optional full sync view (assuming you are using this from previous code)
    path('sync-all/', views.sync_all_to_google_sheet, name='sync_all'),
]