from django.urls import path
from finance import cash_views as views
urlpatterns=[
    path('finance/receivables/',views.receivables,name='cash_receivables'),
    path('finance/cash/',views.listing,name='cash_list'),
    path('finance/cash/<int:pk>/',views.detail,name='cash_detail'),
    path('finance/cash/<int:pk>/review/',views.review,name='cash_review'),
    path('finance/cash/<int:pk>/reverse/',views.reversal,name='cash_reversal'),
    path('invoices/<int:pk>/cash-request/',views.invoice_request,name='cash_invoice_request'),
    path('equipment/events/<int:pk>/expense/',views.expense_request,name='cash_equipment_request'),
]
