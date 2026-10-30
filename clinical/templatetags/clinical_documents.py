"""Display frozen ISO evidence times in the existing business timezone."""
from datetime import datetime
from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def clinical_time(value):
    if not value:
        return '尚未结束'
    return timezone.localtime(datetime.fromisoformat(value)).strftime('%Y-%m-%d %H:%M:%S')
