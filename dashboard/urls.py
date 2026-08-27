from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='dashboard-home'),
    path('api/contacts/list/', views.contacts_list, name='contacts-list'),
    path('api/contacts/count/', views.contacts_count, name='contacts-count'),
    path('api/diagnostics/', views.diagnostics, name='diagnostics'),
    path('api/contacts/add/', views.add_contact, name='add-contact'),
    path('api/contacts/upload/', views.upload_contacts, name='upload-contacts'),
    path('api/contacts/delete/', views.delete_contact, name='delete-contact'),
    path('api/csv/list/', views.csv_files_list, name='csv-files-list'),
    path('api/csv/count/', views.csv_files_count, name='csv-files-count'),
    path('api/csv/download/<str:category>/<str:filename>/', views.csv_file_download, name='csv-file-download'),
    path('api/csv/delete/', views.csv_file_delete, name='csv-file-delete'),

    # Gmail Settings (per-user SMTP configuration)
    path('gmail-settings/', views.gmail_settings_page, name='gmail-settings-page'),
    path('api/gmail/save/', views.gmail_settings_save, name='gmail-settings-save'),
    path('api/gmail/test/', views.gmail_settings_test, name='gmail-settings-test'),
    path('api/gmail/status/', views.gmail_settings_status, name='gmail-settings-status'),
]
