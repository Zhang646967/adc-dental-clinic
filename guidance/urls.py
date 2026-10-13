from django.urls import path
from guidance import views
urlpatterns=[path('guide/',views.index,name='guide_index'),path('guide/<slug:key>/',views.task,name='guide_task')]

from guidance.result_views import wait_result
urlpatterns += [path("guide/result/wait/<int:pk>/", wait_result, name="guide_result_wait")]
