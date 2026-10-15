from django.urls import path
from finance import daily_views as views
urlpatterns=[
    path('finance/daily-closes/',views.listing,name='daily_close_list'),
    path('finance/daily-closes/new/',views.request_close,name='daily_close_request'),
    path('finance/daily-closes/<int:pk>/',views.detail,name='daily_close_detail'),
    path('finance/daily-closes/<int:pk>/review/',views.review_close,name='daily_close_review'),
]
