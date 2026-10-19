from django.urls import path
from operations import cancellation_views as views

urlpatterns = [
    path('operations/cancellations/', views.analysis, name='cancellation_analysis'),
    path('operations/cancellations/followups/', views.followups, name='cancellation_followups'),
    path('operations/cancellations/followups/<int:pk>/', views.followup, name='cancellation_followup'),
    path('operations/improvements/', views.improvements, name='appointment_improvements'),
    path('operations/improvements/new/', views.improvement_new, name='appointment_improvement_new'),
    path('operations/improvements/<int:pk>/', views.improvement_detail, name='appointment_improvement_detail'),
    path('operations/improvements/<int:pk>/<str:action>/', views.improvement_step, name='appointment_improvement_step'),
]
