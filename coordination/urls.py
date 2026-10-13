from django.urls import path
from coordination import views
urlpatterns=[path('waitlist/',views.listing,name='waitlist'),path('waitlist/join/',views.join,name='waitlist_join'),
 path('waitlist/<int:pk>/withdraw/',views.withdraw,name='waitlist_withdraw'),path('waitlist/offers/<int:pk>/',views.offer,name='wait_offer'),
 path('waitlist/recycle/',views.recycle,name='expire_offers'),path('scheduling/plans/',views.plans,name='schedule_plans'),path('scheduling/plans/<int:pk>/',views.plan,name='schedule_plan')]
