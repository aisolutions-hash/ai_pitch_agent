from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('', include('dashboard.urls')),
    path('scraper/', include('scraper.urls')),

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