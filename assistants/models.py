from django.db import models

class UsageBucket(models.Model):
    key=models.CharField(max_length=100,unique=True)
    used=models.PositiveIntegerField(default=0)
    class Meta:
        db_table="adc_ai_usage_bucket"

class AssistantEvent(models.Model):
    request_id=models.UUIDField(unique=True,editable=False)
    user=models.ForeignKey("accounts.UserAccount",on_delete=models.PROTECT)
    audience=models.CharField(max_length=12)
    intent=models.CharField(max_length=32)
    mode=models.CharField(max_length=24)
    result_code=models.CharField(max_length=40,blank=True,default="")
    input_chars=models.PositiveIntegerField()
    duration_ms=models.PositiveIntegerField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table="adc_assistant_event"
        ordering=["-created_at"]
