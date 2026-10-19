from django.urls import path
from reception import views
urlpatterns=[path('reception/',views.listing,name='reception_list'),path('reception/new/',views.create,name='reception_create'),
    path('reception/<int:pk>/',views.detail,name='reception_detail')]
