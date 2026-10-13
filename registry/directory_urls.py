from django.urls import path
from registry import directory_views as v
urlpatterns = [
    path('directory/',v.home,name='directory_home'),
    path('directory/confirm/',v.confirm,name='directory_confirm'),
    path('directory/dentists/<int:pk>/qualifications/',v.attach,name='directory_attach'),
    path('directory/dentists/<int:pk>/qualifications/<int:qpk>/withdraw/',v.withdraw_preview,name='directory_withdraw_preview'),
    path('directory/<str:kind>/',v.listing,name='directory_list'),
    path('directory/<str:kind>/new/',v.create,name='directory_create'),
    path('directory/<str:kind>/<int:pk>/',v.detail,name='directory_detail'),
]
