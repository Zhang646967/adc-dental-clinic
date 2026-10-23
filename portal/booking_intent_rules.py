"""A service selection is navigation only, never a role or booking authority."""
INTENT_KEY = 'adc_booking_intent'
INTENT_SALT = 'adc.portal.service-intent.v1'
INTENT_SECONDS = 600


def selected_service(payload, *, user_id, workspace_id):
    if type(payload) is not dict or set(payload) != {'uid', 'workspace', 'service'}:
        return None
    if type(payload['uid']) is not int or payload['uid'] != user_id:
        return None
    if not isinstance(payload['workspace'], str) or payload['workspace'] != str(workspace_id):
        return None
    service = payload['service']
    if type(service) is not int or not 0 < service < 10**18:
        return None
    return service
