from django.urls import path
from insurance import views
from insurance import settlement_views
from insurance import cancellation_views

urlpatterns = [
    path('insurance/settlements/<int:pk>/cancel/', cancellation_views.create, name='insurance_cancellation_new'),
    path('insurance/settlements/<int:pk>/cancel/query/', cancellation_views.query, name='insurance_cancellation_query'),
    path('insurance/settlements/<int:pk>/cancel/review/', cancellation_views.review, name='insurance_cancellation_review'),
    path('insurance/settlements/', settlement_views.listing, name='insurance_settlements'),
    path('insurance/invoices/<int:pk>/settle/', settlement_views.create, name='insurance_settlement_new'),
    path('insurance/settlements/<int:pk>/', settlement_views.detail, name='insurance_settlement_detail'),
    path('insurance/settlements/<int:pk>/query/', settlement_views.query, name='insurance_settlement_query'),
    path('insurance/settlements/<int:pk>/review/', settlement_views.review, name='insurance_settlement_review'),
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
