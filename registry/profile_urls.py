from django.urls import path
from registry import profile_views as v
urlpatterns=[
    path('profiles/',v.home,name='profile_home'),
    path('profiles/coordination/',v.coordination,name='profile_coordination'),
    path('profiles/confirm/',v.confirm,name='profile_confirm'),
    path('profiles/affiliations/',v.affiliation,name='profile_affiliation'),
    path('profiles/affiliations/confirm/',v.affiliation_confirm,name='profile_affiliation_confirm'),
    path('profiles/review/confirm/',v.review_confirm,name='profile_review_confirm'),
    path('profiles/affiliations/<int:pk>/<str:action>/',v.roster_transition,name='profile_roster_transition'),
    path('profiles/review/<int:pk>/',v.review,name='profile_review'),
    path('profiles/media/<int:pk>/',v.media,name='profile_media'),
    path('profiles/<str:kind>/edit/',v.edit,name='profile_edit'),
    path('profiles/<str:kind>/upload/',v.upload,name='profile_upload'),
    path('profiles/<str:kind>/<str:action>/',v.transition,name='profile_transition'),
]
