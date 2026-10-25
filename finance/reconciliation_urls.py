from django.urls import path
from finance import reconciliation_views as v
from finance import fund_views as funds
from finance import allocation_views as allocations

urlpatterns=[
    path('finance/fund-claims/',allocations.claim_list,name='fund_claims'),
    path('finance/fund-claims/<int:pk>/',allocations.claim_detail,name='fund_claim_detail'),
    path('finance/fund-claims/<int:pk>/issues/new/',allocations.issue_new,name='fund_issue_new'),
    path('finance/fund-issues/',allocations.issue_list,name='fund_issues'),
    path('finance/fund-issues/<int:pk>/',allocations.issue_detail,name='fund_issue_detail'),
    path('finance/fund-issues/<int:pk>/follow/',allocations.followup,name='fund_issue_followup'),
    path('finance/funds/<int:pk>/allocate/',allocations.create,name='fund_allocation_new'),
    path('finance/fund-allocations/<int:pk>/',allocations.detail,name='fund_allocation_detail'),
    path('finance/fund-allocations/<int:pk>/review/',allocations.review,name='fund_allocation_review'),
    path('finance/funds/',funds.listing,name='fund_transfers'),
    path('finance/funds/lines/<int:pk>/record/',funds.create,name='fund_transfer_new'),
    path('finance/funds/<int:pk>/',funds.detail,name='fund_transfer_detail'),
    path('finance/funds/<int:pk>/review/',funds.review,name='fund_transfer_review'),
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
