from django.contrib.auth import views as auth_views
from django.urls import path, include
from workspaces.views import WorkspaceLoginView
from adc_core import views
from portal import views as portal_views
from care import views as care_views
from assistants import views as ai_views
from finance import views as finance_views
from operations import views as operations_views
from care import correction_views

urlpatterns = [
    path("", include("finance.daily_urls")),
    path("", include("equipment.urls")),
    path("", include("finance.cash_urls")),
    path("", include("notifications.urls")),
    path("", include("coordination.task_urls")),
    path("", include("scheduling.front_coordination_urls")),
    path("", include("scheduling.availability_urls")),
    path("", include("registry.directory_urls")),
    path("", include("patients.contact_urls")),
    path("", include("registry.catalog_urls")),
    path('', include('accounts.governance_urls')),
    path("", include("workspaces.urls")),
    path("", include("coordination.urls")),
    path("", include("guidance.urls")),
    path("finance/", finance_views.quarters, name="finance_quarters"),
    path("finance/<int:pk>/", finance_views.detail, name="quarter_detail"),
    path("finance/<int:pk>/cost/<int:cost_pk>/", finance_views.cost, name="quarter_cost"),
    path("finance/<int:pk>/export/", finance_views.export, name="quarter_export"),
    path("operations/", operations_views.dashboard, name="operations_dashboard"),
    path("corrections/", correction_views.listing, name="corrections"),
    path("care/<int:pk>/correction/", correction_views.create, name="correction_create"),
    path("corrections/<int:pk>/", correction_views.detail, name="correction_detail"),
    path("portal/login/", portal_views.PortalLoginView.as_view(), name="portal_login"),
    path("portal/", portal_views.home, name="portal_home"),
    path("portal/appointments/", portal_views.appointments, name="portal_appointments"),
    path("portal/slots/", portal_views.slots, name="portal_slots"),
    path("portal/book/confirm/", portal_views.booking_preview, name="portal_confirm"),
    path("portal/visits/<int:pk>/", portal_views.visit, name="portal_visit"),
    path("portal/visits/<int:pk>/cancel/", portal_views.cancel, name="portal_cancel"),
    path("portal/invoices/<int:pk>/", care_views.portal_invoice, name="portal_invoice"),
    path("portal/help/", portal_views.help_page, name="portal_help"),
    path("portal/assistant/", ai_views.patient_page, name="portal_assistant"),
    path("assistant/", ai_views.staff_page, name="staff_assistant"),
    path("api/assistant/<str:audience>/", ai_views.chat_api, name="assistant_api"),
    path("care/<int:pk>/", care_views.workspace, name="care_workspace"),
    path("care/<int:pk>/complete/", care_views.complete, name="care_complete"),
    path("invoices/<int:pk>/", care_views.invoice_detail, name="invoice_detail"),
    path("health/", views.health, name="health"),
    path("accounts/login/", WorkspaceLoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("patients/", views.patient_list, name="patients"),
    path("patients/new/", views.patient_create, name="patient_create"),
    path("patients/lookup/", views.patient_lookup, name="patient_lookup"),
    path("patients/<int:pk>/", views.patient_detail, name="patient_detail"),
    path("visits/", views.visit_list, name="visits"),
    path("visits/new/", views.visit_create, name="visit_create"),
    path("visits/<int:pk>/", views.visit_detail, name="visit_detail"),
    path("visits/<int:pk>/reschedule/", views.visit_reschedule, name="visit_reschedule"),
    path("slots/new/", views.slot_create, name="slot_create"),
]
