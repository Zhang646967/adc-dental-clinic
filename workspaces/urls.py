from django.urls import path
from workspaces import views
urlpatterns=[
 path('workspace/select-role/',views.select_role,name='select_role'),
 path('workspace/activate/',views.activate_role,name='activate_role'),
 path('workspace/select-clinic/',views.select_clinic,name='select_clinic'),
 path('workspace/clinic/activate/',views.activate_clinic,name='activate_clinic'),
 path('doctor/',views.home,name='doctor_home'),path('frontdesk/',views.home,name='frontdesk_home'),
 path('manager/',views.home,name='manager_home'),path('headquarters/',views.home,name='hq_home'),
 path('financial-workspace/',views.home,name='finance_home'),path('technical/',views.home,name='technical_home'),
]
