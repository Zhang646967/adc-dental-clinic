from django.urls import path
from finance import cash_views as views
from finance import advance_views as advances
urlpatterns=[
    path('finance/receivables/',views.receivables,name='cash_receivables'),
    path('finance/cash/',views.listing,name='cash_list'),
    path('finance/cash/<int:pk>/',views.detail,name='cash_detail'),
    path('finance/cash/<int:pk>/review/',views.review,name='cash_review'),
    path('finance/cash/<int:pk>/reverse/',views.reversal,name='cash_reversal'),
    path('finance/cash/<int:pk>/advance-refund/',views.advance_refund,name='cash_advance_refund'),
    path('invoices/<int:pk>/cash-request/',views.invoice_request,name='cash_invoice_request'),
    path('patients/<int:pk>/advance-request/',views.advance_request,name='cash_advance_request'),
    path('finance/advance-allocations/', advances.listing, name='advance_allocation_list'),
    path('finance/advance-allocations/<int:pk>/', advances.detail, name='advance_allocation_detail'),
    path('finance/advance-allocations/<int:pk>/review/', advances.review, name='advance_allocation_review'),
    path('finance/advance-allocation-lines/<int:pk>/reverse/', advances.reverse_line, name='advance_reverse_line'),
    path('finance/advance-reversals/', advances.reversal_list, name='advance_reversal_list'),
    path('finance/advance-reversals/<int:pk>/', advances.reversal_detail, name='advance_reversal_detail'),
    path('finance/advance-reversals/<int:pk>/review/', advances.reversal_review, name='advance_reversal_review'),
    path('finance/cash/<int:pk>/allocate/', advances.new, name='advance_allocation_new'),
    path('equipment/events/<int:pk>/expense/',views.expense_request,name='cash_equipment_request'),
]
