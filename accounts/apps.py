from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        import logging
        logging.captureWarnings(True)
        from django.contrib.auth.signals import user_logged_in, user_login_failed, user_logged_out
        from adc_core import request_trace
        for signal, receiver in ((user_logged_in, request_trace.login_success),
                                 (user_login_failed, request_trace.login_failed),
                                 (user_logged_out, request_trace.logout)):
            signal.connect(receiver, dispatch_uid='adc.safe.' + receiver.__name__)
