from django.urls import path
from clinical import prescription_views as views

urlpatterns = [
    path('pharmacy/review/', views.review_queue, name='prescription_review_queue'),
    path('pharmacy/visits/<int:pk>/', views.visit_prescription, name='prescription_visit'),
    path('pharmacy/prescriptions/<int:pk>/', views.detail, name='prescription_detail'),
    path('pharmacy/confirm/', views.confirm, name='prescription_confirm'),
]
