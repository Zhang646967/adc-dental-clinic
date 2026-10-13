"""Loopback-only RC course instance, not internet production settings."""
import os
from django.core.exceptions import ImproperlyConfigured
if os.environ.get('ADC_RC_SYNTHETIC') != '1':
    raise ImproperlyConfigured('Explicit synthetic course instance required.')
from .base import *
DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]']
SESSION_COOKIE_AGE = 3600
DATABASES['default']['OPTIONS']['options'] = '-c statement_timeout=30000 -c lock_timeout=8000'
# Gunicorn is reached only by the private, loopback-published gateway.
SECURE_REFERRER_POLICY = 'same-origin'
