from django.urls import path
from scheduling import front_coordination_views as views
urlpatterns = [
    path('front/coordination/', views.listing, name='front_coordination_list'),
    path('front/coordination/slots/<int:pk>/', views.detail, name='front_coordination_detail'),
]
