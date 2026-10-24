from .base import *
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
# Speed-up applies only to synthetic automated test fixtures.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
ADC_READ_ONLY = False
# Only this isolated fixture configuration retains the pre-activation demo scope.
# Non-synthetic settings enforce professional authority even for a new clinic.
ADC_CLINICAL_SYNTHETIC = True

# Tests never invoke or spend on a configured external AI provider.
AI_MODE = "demo"
AI_API_KEY = ""
