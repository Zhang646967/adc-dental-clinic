from django.urls import path
from registry import catalog_views as v
urlpatterns=[path('catalogue/treatments/',v.listing,name='catalogue_list'),
path('catalogue/treatments/new/',v.create,name='catalogue_create'),
path('catalogue/treatments/<int:pk>/price/',v.price,name='catalogue_price')]
