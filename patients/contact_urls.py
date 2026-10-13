from django.urls import path
from patients import contact_views
urlpatterns = [
    path('patients/<int:pk>/contact/', contact_views.edit, name='patient_contact_edit'),
    path('patients/<int:pk>/contact/confirm/', contact_views.confirm, name='patient_contact_confirm'),
]
