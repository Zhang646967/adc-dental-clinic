from django.urls import path
from portal import relationship_views as v
urlpatterns=[
 path('patients/relationships/',v.listing,name='patient_relationships'),
 path('patients/relationships/new/',v.create,name='patient_relationship_create'),
 path('patients/relationships/confirm/',v.confirm,name='patient_relationship_confirm'),
 path('patients/relationships/<int:pk>/',v.detail,name='patient_relationship_detail'),
 path('patients/relationships/<int:pk>/<str:action>/',v.action,name='patient_relationship_action'),
 path('portal/patients/',v.subjects,name='portal_subjects'),
]
