from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', include('dashboard.urls')),
    path('scraper/', include('scraper.urls')),
    
    path('admin/', admin.site.urls),

    # App 1: Extractor
    path('search/', include('extractor.urls')),

    # App 2: AI Pitch Agent (The original one)
    path('pitch/', include('ai_agent_pitch.urls')),

    # App 3: Pitch Generator (The NEW one you just built)
    path('generator/', include('pitch_generator.urls')),
]

# Serve static files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / 'static')