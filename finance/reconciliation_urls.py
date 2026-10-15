from django.urls import path
from finance import reconciliation_views as v

urlpatterns=[
    path('finance/payment-accounts/',v.accounts,name='payment_accounts'),
    path('finance/payment-accounts/new/',v.account_edit,name='payment_account_new'),
    path('finance/payment-accounts/<int:pk>/state/',v.account_edit,name='payment_account_state'),
    path('finance/reconciliation/',v.home,name='reconciliation_home'),
    path('finance/reconciliation/template/',v.template,name='statement_template'),
    path('finance/reconciliation/import/',v.import_statement,name='statement_import'),
    path('finance/reconciliation/batches/<int:pk>/',v.batch_detail,name='statement_batch'),
    path('finance/reconciliation/lines/<int:pk>/',v.match_line,name='statement_match'),
    path('finance/reconciliation/matches/<int:pk>/',v.match_detail,name='reconciliation_match'),
    path('finance/reconciliation/matches/<int:pk>/review/',v.match_review,name='reconciliation_review'),
    path('finance/cash/<int:pk>/evidence/',v.evidence_edit,name='cash_evidence_edit'),
    path('finance/evidence/<int:pk>/review/',v.evidence_review,name='cash_evidence_review'),
]
