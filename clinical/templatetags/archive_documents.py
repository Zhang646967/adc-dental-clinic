from django import template
from clinical.archive_display import sections,flatten,changes
register=template.Library()
register.filter('archive_sections',sections)
register.filter('archive_fields',lambda value:list(flatten(value)))
register.filter('archive_changes',changes)
