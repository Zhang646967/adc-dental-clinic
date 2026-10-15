from django.urls import path
from equipment import views
urlpatterns=[
    path('equipment/expenses/',views.expenses,name='equipment_expenses'),
    path('equipment/<int:pk>/schedule/',views.schedule,name='equipment_schedule'),
    path('equipment/',views.listing,name='equipment_list'),
    path('equipment/register/',views.register,name='equipment_register'),
    path('equipment/<int:pk>/',views.detail,name='equipment_detail'),
    path('equipment/<int:pk>/change/',views.change,name='equipment_change'),
]
