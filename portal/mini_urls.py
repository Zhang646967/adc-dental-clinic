from django.urls import path
from portal import mini_api as api

urlpatterns = [
    path('session/', api.session, name='mini_session'),
    path('login/', api.sign_in, name='mini_login'),
    path('logout/', api.sign_out, name='mini_logout'),
    path('catalogue/', api.catalogue, name='mini_catalogue'),
    path('candidates/', api.candidates, name='mini_candidates'),
    path('visits/', api.visits, name='mini_visits'),
    path('visits/<int:pk>/', api.detail, name='mini_visit'),
    path('booking/preview/', api.book_preview, name='mini_book_preview'),
    path('booking/confirm/', api.book_confirm, name='mini_book_confirm'),
    path('visits/<int:pk>/cancel/preview/', api.cancel_preview, name='mini_cancel_preview'),
    path('visits/<int:pk>/cancel/confirm/', api.cancel_confirm, name='mini_cancel_confirm'),
    path('visits/<int:pk>/reschedule/candidates/', api.reschedule_candidates, name='mini_reschedule_candidates'),
    path('visits/<int:pk>/reschedule/preview/', api.reschedule_preview, name='mini_reschedule_preview'),
    path('visits/<int:pk>/reschedule/confirm/', api.reschedule_confirm, name='mini_reschedule_confirm'),
]
