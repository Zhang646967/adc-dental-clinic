from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL),
                    ("patients", "0001_initial"), ("scheduling", "0001_initial")]
    operations = [
        migrations.CreateModel(name="PatientAccess", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("is_active", models.BooleanField(default=True)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="patient_access", to=settings.AUTH_USER_MODEL)),
            ("patient", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="portal_access", to="patients.patient")),
        ], options={"db_table":"adc_patient_access"}),
        migrations.CreateModel(name="BookingReceipt", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("nonce", models.UUIDField(unique=True, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("access", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="portal.patientaccess")),
            ("visit", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, to="scheduling.visit")),
        ], options={"db_table":"adc_portal_booking_receipt"}),
    ]
