from django.urls import path
from coordination import task_views as views
urlpatterns=[
    path('coordination/tasks/',views.listing,name='coordination_task_list'),
    path('coordination/tasks/slots/<int:slot_id>/new/',views.change,name='coordination_task_open'),
    path('coordination/tasks/slots/<int:slot_id>/new/confirm/',views.confirm,name='coordination_task_confirm_new'),
    path('coordination/tasks/slots/<int:slot_id>/<int:task_id>/',views.detail,name='coordination_task_detail'),
    path('coordination/tasks/slots/<int:slot_id>/<int:task_id>/act/<str:action>/',views.change,name='coordination_task_action'),
    path('coordination/tasks/slots/<int:slot_id>/<int:task_id>/confirm/',views.confirm,name='coordination_task_confirm'),
]
