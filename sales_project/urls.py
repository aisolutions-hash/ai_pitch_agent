from django.contrib.auth import views as auth_views
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from sales_project import views

handler400 = 'sales_project.error_handlers.bad_request'
handler403 = 'sales_project.error_handlers.permission_denied'
handler404 = 'sales_project.error_handlers.page_not_found'
handler500 = 'sales_project.error_handlers.server_error'

urlpatterns = [
    path('', TemplateView.as_view(template_name='landing.html'), name='landing'),
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', views.custom_logout, name='logout'),
    path('signup/', views.signup, name='signup'),
    path('password-reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    
    # Authenticated user workspace
    path('app/', include('dashboard.urls')),
    path('app/scraper/', include('scraper.urls')),
    path('app/search/', include('extractor.urls')),
    path('app/pitch/', include('ai_agent_pitch.urls')),
    path('app/generator/', include('pitch_generator.urls')),
]