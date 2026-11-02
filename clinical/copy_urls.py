from django.urls import path
from clinical import copy_views as views

urlpatterns=[
 path('portal/record-copies/',views.patient_list,name='portal_record_copies'),
 path('portal/record-copies/new/',views.apply,name='portal_record_copy_new'),
 path('portal/record-copies/confirm/',views.confirm,name='portal_record_copy_confirm'),
 path('portal/record-copies/download/',views.download,name='portal_record_copy_download'),
 path('portal/record-copies/<int:pk>/',views.detail,name='portal_record_copy'),
 path('clinical/record-copies/',views.staff_list,name='record_copies'),
 path('clinical/record-copies/new/',views.apply,{'staff':True},name='record_copy_new'),
 path('clinical/record-copies/confirm/',views.confirm,{'staff':True},name='record_copy_confirm'),
 path('clinical/record-copies/<int:pk>/',views.detail,{'staff':True},name='record_copy_detail'),
]
