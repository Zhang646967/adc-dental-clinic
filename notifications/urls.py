from django.urls import path
from notifications import views
urlpatterns=[
    path('notifications/',views.inbox,name='notification_inbox'),
    path('notifications/<int:message_id>/read/',views.acknowledge,name='notification_read'),
    path('notifications/delivery/',views.status,name='notification_status'),
    path('notifications/delivery/<int:event_id>/retry/',views.retry,name='notification_retry'),
]
