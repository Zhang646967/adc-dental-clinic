"""Stable expression used by historical migrations; preserve its import path."""
from django.db import models
from django.contrib.postgres.fields import DateTimeRangeField
class TsTzRange(models.Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()
