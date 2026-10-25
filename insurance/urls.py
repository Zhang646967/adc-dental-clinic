from django.urls import path
from insurance import views

urlpatterns = [
    path('insurance/', views.home, name='insurance_home'),
    path('insurance/catalogues/new/', views.import_catalogue, name='insurance_import'),
    path('insurance/catalogues/<int:pk>/', views.catalogue, name='insurance_catalogue'),
    path('insurance/catalogues/<int:pk>/source/', views.source_download, name='insurance_source'),
    path('insurance/catalogues/<int:pk>/resubmit/', views.resubmit_catalogue, name='insurance_resubmit'),
    path('insurance/arrangements/new/', views.arrangement_new, name='insurance_arrangement_new'),
    path('insurance/mappings/new/', views.mapping_new, name='insurance_mapping_new'),
    path('insurance/patients/<int:pk>/', views.eligibility, name='insurance_eligibility'),
    path('insurance/<str:kind>/<int:pk>/', views.detail, name='insurance_detail'),
    path('insurance/<str:kind>/<int:pk>/review/', views.review, name='insurance_review'),
    path('insurance/<str:kind>/<int:pk>/disable/', views.disable, name='insurance_disable'),
]
