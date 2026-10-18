"""Candidate WSGI settings. Listener must remain on the private proxy network."""
bind='0.0.0.0:8000'
workers=2
worker_class='sync'
timeout=30
graceful_timeout=30
keepalive=2
limit_request_line=4094
limit_request_fields=50
limit_request_field_size=4096
max_requests=500
max_requests_jitter=50
accesslog='-'
# Do not include queries, cookies, authorization, form content or patient IDs.
access_log_format='%(m)s %(s)s %(L)s'
errorlog='-'
loglevel='warning'
from adc_core.operational_logging import logging_config
logconfig_dict = logging_config()
