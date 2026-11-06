from django.urls import path
from . import views

app_name = 'agents'

urlpatterns = [
    path('complete-profile/', views.complete_profile, name='complete_profile'),
    path('add/', views.add_agent, name='add_agent'),
    path('list/', views.agent_list, name='agent_list'),
    path('<int:agent_id>/', views.agent_detail, name='agent_detail'),
    path('stream_cam/<int:zone_id>', views.stream_superviseur, name='stream_cam'),
    path('video_feed/<int:cam_id>/', views.video_feed, name='video_feed'),
    path('api/alert_status/<int:cam_id>/', views.check_camera_alert, name='check_camera_alert'),
]