from django.urls import path
from scheduling import resource_views as v
urlpatterns=[path('scheduling/resources/map/',v.mapping,name='resource_mapping'),path('scheduling/resources/',v.catalogue,name='resource_catalogue'),
    path('scheduling/resources/config/<str:kind>/',v.configuration,name='resource_config'),
    path('scheduling/resources/candidates/',v.candidate_list,name='resource_candidates'),
    path('scheduling/resources/coordination/',v.coordination_list,name='resource_coordination_list'),
    path('scheduling/resources/coordination/<int:pk>/',v.coordination_detail,name='resource_coordination_detail'),
    path('scheduling/resources/summary/',v.summary,name='resource_summary')]
