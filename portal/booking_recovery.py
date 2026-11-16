"""Recover a booking or replacement from the original authorized receipt."""
from django import forms
from django.http import JsonResponse
from django.urls import reverse

from portal import rescheduling, services

RESULT_WINDOW_SECONDS = 3600


class BookingResultForm(forms.Form):
    kind = forms.ChoiceField(choices=(('booking', '预约'), ('reschedule', '改期')))
    proposal_token = forms.CharField(max_length=16384)


def outcome(actor, kind, token):
    read = services.booking_result if kind == 'booking' else rescheduling.reschedule_result
    visit_id = read(actor=actor, token=token, max_age=RESULT_WINDOW_SECONDS)
    if visit_id is None:
        return {'state': 'UNCONFIRMED'}
    return {'state': 'SAVED', 'visit_id': visit_id}


def web_reply(data, *, status=200):
    if data['state'] == 'SAVED':
        data = dict(data, url=reverse('portal_visit', args=[data['visit_id']]))
    response = JsonResponse(data, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def web_rejection(form):
    errors = [str(message) for field in form.errors.values() for message in field]
    return web_reply({'state': 'REJECTED', 'message': ' '.join(errors)}, status=409)
