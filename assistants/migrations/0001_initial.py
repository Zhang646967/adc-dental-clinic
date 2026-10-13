from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion
class Migration(migrations.Migration):
    initial=True
    dependencies=[migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
      migrations.CreateModel(name="UsageBucket",fields=[
        ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
        ("key",models.CharField(max_length=100,unique=True)),("used",models.PositiveIntegerField(default=0))
      ],options={"db_table":"adc_ai_usage_bucket"}),
      migrations.CreateModel(name="AssistantEvent",fields=[
        ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
        ("request_id",models.UUIDField(unique=True,editable=False)),
        ("audience",models.CharField(max_length=12)),("intent",models.CharField(max_length=32)),
        ("mode",models.CharField(max_length=24)),("result_code",models.CharField(max_length=40,blank=True,default="")),
        ("input_chars",models.PositiveIntegerField()),("duration_ms",models.PositiveIntegerField()),
        ("created_at",models.DateTimeField(auto_now_add=True)),
        ("user",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL))
      ],options={"db_table":"adc_assistant_event","ordering":["-created_at"]}),
    ]
