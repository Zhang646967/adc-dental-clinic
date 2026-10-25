from django.urls import path
from portal import account_views as views
from portal import auth_views as auth

urlpatterns=[
    path('portal/auth/sms/',auth.sms,name='patient_sms_login'),
    path('portal/account/phone/sms/',auth.sms,{'binding':True},name='patient_sms_bind'),
    path('portal/auth/wechat/start/',auth.wechat_start,name='patient_wechat_start'),
    path('portal/auth/wechat/callback/',auth.wechat_callback,name='patient_wechat_callback'),
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
