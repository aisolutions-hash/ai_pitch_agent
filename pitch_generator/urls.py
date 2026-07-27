from django.urls import path
from . import views

app_name = 'pitch_generator'

urlpatterns = [
    path('create/', views.create_pitch, name='create_pitch'),
    path('result/<int:pitch_id>/', views.view_pitch, name='view_pitch'),
]