# projects/urls.py
from django.urls import path
from . import views

app_name = 'projects'

urlpatterns = [
    path('create/', views.create_project, name='create_project'),
    path('add_zone/<int:project_id>', views.add_zone, name='add_zone'),
    path('add_cam/<str:name_zone>', views.add_cam, name='add_cam'),

    path('list/', views.project_list, name='project_list'),
    path('<int:project_id>/', views.project_detail, name='project_detail'),
    path('<int:project_id>/update/', views.update_project, name='update_project'),
    path('<int:project_id>/assign_agents/', views.assign_agents, name='assign_agents'),
    path('zones/<int:zone_id>/assign_agents/', views.assign_zone_agents, name='assign_zone_agents'),
    path('zones/<int:zone_id>/switch_cam/<int:cam_id>/', views.switch_active_camera, name='switch_camera'),
    path('<int:project_id>/toggle_patrol/', views.toggle_patrol_status, name='toggle_patrol'),
    path('<int:project_id>/delete/', views.delete_project, name='delete_project'),
    path('alerts/', views.alert_list, name='alert_list'),
    path('alerts/<int:alert_id>/review/', views.review_alert, name='review_alert'),
    path('api/alerts/latest/', views.api_latest_alerts, name='api_latest_alerts'),
    path('api/settings/ai/', views.api_ai_settings, name='api_ai_settings'),
]