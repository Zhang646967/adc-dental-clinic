from django.urls import path
from clinical import views
from clinical import encounter_views as encounters

urlpatterns=[
    path('clinical/worklist/',encounters.worklist,name='clinical_worklist'),
    path('clinical/encounters/<int:pk>/',encounters.workspace,name='clinical_encounter'),
    path('clinical/encounters/<int:pk>/history/',encounters.interview_history,name='clinical_interview_history'),
    path('clinical/encounters/<int:pk>/confirm/',encounters.record_preview,name='clinical_record_preview'),
    path('clinical/records/confirm/',encounters.record_confirm,name='clinical_record_confirm'),
    path('portal/history/',encounters.patient_history,name='portal_history'),
    path('clinical/authority/',views.authority_home,name='clinical_authority_home'),
    path('clinical/authority/new/',views.authority_new,name='clinical_authority_new'),
    path('clinical/authority/activate/',views.authority_activate,name='clinical_authority_activate'),
    path('clinical/authority/confirm/',views.authority_confirm,name='clinical_authority_confirm'),
    path('clinical/authority/<int:pk>/',views.authority_detail,name='clinical_authority_detail'),
    path('clinical/authority/<int:pk>/<str:action>/',views.authority_action,name='clinical_authority_action'),
    path('clinical/referrals/',views.referral_home,name='clinical_referrals'),
    path('clinical/referrals/new/<int:pk>/',views.referral_new,name='clinical_referral_new'),
    path('clinical/referrals/confirm/',views.referral_confirm,name='clinical_referral_confirm'),
    path('clinical/referrals/<int:pk>/',views.referral_detail,name='clinical_referral_detail'),
    path('clinical/referrals/<int:pk>/record/',views.referral_record,name='clinical_referral_record'),
    path('clinical/referrals/<int:pk>/<str:action>/',views.referral_action,name='clinical_referral_action'),
]
