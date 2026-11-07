from django.urls import path

from supplies import views

urlpatterns=[
    path('supplies/stock/',views.stock_queue,name='stock_queue'),
    path('supplies/stock/receive/',views.stock_receive,name='stock_receive'),
    path('supplies/stock/<int:pk>/',views.stock_detail,name='stock_detail'),
    path('supplies/nursing/',views.nursing_queue,name='nursing_queue'),
    path('supplies/nursing/<int:pk>/',views.nursing_detail,name='nursing_detail'),
    path('supplies/nursing/sterile/',views.sterile_packs,name='sterile_packs'),
]
