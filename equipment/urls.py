from django.urls import path
from equipment import views
urlpatterns=[
    path('equipment/',views.listing,name='equipment_list'),
    path('equipment/register/',views.register,name='equipment_register'),
    path('equipment/<int:pk>/',views.detail,name='equipment_detail'),
    path('equipment/<int:pk>/change/',views.change,name='equipment_change'),
]
