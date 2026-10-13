from django.urls import path
from scheduling import availability_views as views
from scheduling import intake_views
urlpatterns=[
    path('slots/<int:pk>/intake/<str:action>/',intake_views.change,name='intake_change'),
    path('slots/<int:pk>/intake-confirm/',intake_views.confirm,name='intake_confirm'),
    path('slots/',views.listing,name='availability_list'),
    path('slots/<int:pk>/',views.detail,name='availability_detail'),
    path('slots/<int:pk>/change/<str:action>/',views.change,name='availability_change'),
    path('slots/<int:pk>/confirm/',views.confirm,name='availability_confirm'),
]
