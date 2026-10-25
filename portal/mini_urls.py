from django.urls import path
from portal import mini_api as api
from portal import mini_waitlist as wait
from portal import mini_referrals as referral
from portal import mini_history as history
from portal import mini_plans as plans
from portal import mini_discovery as discovery

urlpatterns = [
    path('discovery/',discovery.listing,name='mini_public_discovery'),
    path('discovery/services/<int:pk>/',discovery.service,name='mini_public_service'),
    path('plans/',plans.listing,name='mini_plans'),
    path('plans/<int:pk>/',plans.detail,name='mini_plan'),
    path('plans/<int:pk>/steps/<int:step_id>/decision/preview/',plans.decision_preview,name='mini_plan_decision_preview'),
    path('plans/<int:pk>/steps/<int:step_id>/decision/confirm/',plans.decision_confirm,name='mini_plan_decision_confirm'),
    path('history/',history.listing,name='mini_history'),
    path('history/submit/',history.submit,name='mini_history_submit'),
    path('referrals/',referral.listing,name='mini_referrals'),
    path('referrals/<int:pk>/stop/preview/',referral.stop_preview,name='mini_referral_stop_preview'),
    path('referrals/<int:pk>/stop/confirm/',referral.stop_confirm,name='mini_referral_stop_confirm'),
    path('patients/',api.subjects,name='mini_subjects'),
    path('patients/select/',api.select_subject,name='mini_subject_select'),
    path('session/', api.session, name='mini_session'),
    path('login/', api.sign_in, name='mini_login'),
    path('logout/', api.sign_out, name='mini_logout'),
    path('catalogue/', api.catalogue, name='mini_catalogue'),
    path('services/<int:pk>/', api.service_detail, name='mini_service'),
    path('overview/', api.overview, name='mini_overview'),
    path('waitlist/', wait.listing, name='mini_waitlist'),
    path('waitlist/join/preview/', wait.join_preview, name='mini_wait_join_preview'),
    path('waitlist/join/confirm/', wait.join_confirm, name='mini_wait_join_confirm'),
    path('waitlist/<int:pk>/withdraw/preview/', wait.withdraw_preview, name='mini_wait_withdraw_preview'),
    path('waitlist/<int:pk>/withdraw/confirm/', wait.withdraw_confirm, name='mini_wait_withdraw_confirm'),
    path('offers/<int:pk>/', wait.detail, name='mini_offer'),
    path('offers/<int:pk>/preview/', wait.answer_preview, name='mini_offer_preview'),
    path('offers/<int:pk>/confirm/', wait.answer_confirm, name='mini_offer_confirm'),
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
