from django.urls import path
from finance import management_views as v
urlpatterns=[
    path('operations/management/chain/',v.chain,name='management_chain'),
    path('operations/management/',v.home,name='management_home'),
    path('operations/management/costs/new/',v.cost_new,name='management_cost_new'),
    path('operations/management/action/',v.action,name='management_action'),
    path('operations/management/confirm/',v.confirm,name='management_confirm'),
    path('operations/management/reports/<int:pk>/',v.retained_report,name='management_retained'),
]
