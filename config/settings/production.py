"""Production configuration CANDIDATE, never selected by local Compose.
Setting the input flags is not evidence of HTTPS, restoration or load validation.
Only trusted reverse proxies may reach the application listener.
"""
import os
from django.core.exceptions import ImproperlyConfigured
from config.production_contract import validate_production_inputs
try:
    _deployment = validate_production_inputs(os.environ)
except ValueError as exc:
    raise ImproperlyConfigured(str(exc)) from exc
from .base import *

DEBUG = False
ALLOWED_HOSTS = [_deployment.host]
CSRF_TRUSTED_ORIGINS = ['https://' + _deployment.host]
ADC_READ_ONLY = _deployment.read_only
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 3600
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_REFERRER_POLICY = 'same-origin'
DATABASES['default']['OPTIONS']['sslmode'] = _deployment.sslmode
DATABASES['default']['OPTIONS']['options'] = '-c statement_timeout=15000 -c lock_timeout=5000'
