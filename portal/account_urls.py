from django.urls import path
from portal import account_views as views

urlpatterns=[
    path('portal/local-login/',views.local_login,name='patient_local_login'),
    path('portal/account/',views.account,name='patient_account'),
    path('portal/account/activate/',views.activate,name='patient_account_activate'),
    path('portal/enrollment/new/',views.enrollment_form,name='patient_enrollment_new'),
    path('portal/enrollment/<int:pk>/edit/',views.enrollment_form,name='patient_enrollment_edit'),
    path('portal/enrollment/confirm/',views.enrollment_confirm,name='patient_enrollment_submit_confirm'),
    path('portal/enrollment/<int:pk>/withdraw/',views.enrollment_withdraw,name='patient_enrollment_withdraw'),
    path('patients/enrollments/',views.review_list,name='patient_enrollment_list'),
    path('patients/enrollments/<int:pk>/',views.review_detail,name='patient_enrollment_detail'),
    path('patients/enrollments/confirm/',views.review_confirm,name='patient_enrollment_review_confirm'),
]
