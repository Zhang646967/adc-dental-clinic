from django.urls import path
from equipment import views
from equipment import cost_views
from equipment import maintenance_views as maintenance
urlpatterns=[
    path('equipment/maintenance/',maintenance.listing,name='maintenance_list'),
    path('equipment/<int:asset_id>/maintenance/new/',maintenance.create,name='maintenance_create'),
    path('equipment/maintenance/<int:pk>/',maintenance.detail,name='maintenance_detail'),
    path('equipment/maintenance/<int:pk>/<str:action>/',maintenance.action,name='maintenance_action'),
    path('equipment/cost-reviews/',cost_views.queue,name='equipment_cost_queue'),
    path('equipment/events/<int:pk>/costs/',cost_views.history,name='equipment_cost_history'),
    path('equipment/events/<int:pk>/costs/request/',cost_views.request_cost,name='equipment_cost_request'),
    path('equipment/cost-reviews/<int:pk>/',cost_views.review_cost,name='equipment_cost_review'),
    path('equipment/expenses/',views.expenses,name='equipment_expenses'),
    path('equipment/<int:pk>/schedule/',views.schedule,name='equipment_schedule'),
    path('equipment/',views.listing,name='equipment_list'),
    path('equipment/register/',views.register,name='equipment_register'),
    path('equipment/<int:pk>/',views.detail,name='equipment_detail'),
    path('equipment/<int:pk>/change/',views.change,name='equipment_change'),
]
