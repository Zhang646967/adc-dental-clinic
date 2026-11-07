from django.urls import path
from clinical import prescription_views as views
from clinical import dispensing_views as pharmacy

urlpatterns = [
    path('pharmacy/review/', views.review_queue, name='prescription_review_queue'),
    path('pharmacy/visits/<int:pk>/', views.visit_prescription, name='prescription_visit'),
    path('pharmacy/prescriptions/<int:pk>/', views.detail, name='prescription_detail'),
    path('pharmacy/dispense/', pharmacy.queue, name='dispensing_queue'),
    path('pharmacy/dispense/<int:pk>/', pharmacy.detail, name='dispensing_detail'),
    path('pharmacy/dispense/<int:pk>/confirm/', pharmacy.confirm, name='dispensing_confirm'),
    path('pharmacy/confirm/', views.confirm, name='prescription_confirm'),
]
