from django.urls import path
from accounts import governance_views as views
urlpatterns=[
    path('accounts/password/',views.change_own_password,name='own_password_change'),
    path('technical/accounts/',views.listing,name='account_manage_list'),
    path('technical/accounts/new/',views.create,name='account_manage_create'),
    path('technical/accounts/<int:pk>/',views.detail,name='account_manage_detail'),
    path('technical/accounts/<int:pk>/<str:action>/',views.change,name='account_manage_change'),
]
