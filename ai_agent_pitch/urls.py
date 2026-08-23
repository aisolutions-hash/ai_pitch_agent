from django.urls import path
from . import views

app_name = 'ai_agent_pitch'

urlpatterns = [
    path('', views.pitch_creator_view, name='pitch_creator'),
    
    path('dashboard/', views.dashboard_view, name='dashboard'),
    # *** THIS IS THE NEW, CORRECTED LINE ***
    path('dashboard/<int:campaign_id>/', views.campaign_detail_view, name='campaign_detail'),
    path('get-campaigns/', views.get_campaigns_view, name='get_campaigns'),
    path('mark-opened/<int:campaign_id>/<str:recipient_email>/', views.mark_as_opened_view, name='mark_as_opened'),

    # --- Existing AJAX URLs ---
    path('save-template/', views.save_template_view, name='save_template'),
    path('load-template/<int:template_id>/', views.load_template_view, name='load_template'),
    path('delete-template/<int:template_id>/', views.delete_template_view, name='delete_template'),
    path('generate-subject/', views.generate_subject_view, name='generate_subject'),
    path('enhance-with-ai/', views.enhance_with_ai_view, name='enhance_with_ai'),

    # --- AI Auto Campaign Engine ---
    path('campaign-engine/config/', views.campaign_engine_config_view, name='campaign_engine_config'),
    path('campaign-engine/config/save/', views.campaign_engine_config_save_view, name='campaign_engine_config_save'),
    path('campaign-engine/run/', views.campaign_engine_run_view, name='campaign_engine_run'),
    path('campaign-engine/progress/', views.campaign_engine_progress_view, name='campaign_engine_progress'),
    path('campaign-engine/runs/', views.campaign_engine_runs_view, name='campaign_engine_runs'),
    path('campaign-engine/runs/detail/', views.campaign_engine_run_detail_view, name='campaign_engine_run_detail'),
]
