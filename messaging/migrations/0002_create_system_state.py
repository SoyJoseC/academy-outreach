from django.db import migrations


def create_system_state(apps, schema_editor):
    SystemState = apps.get_model("messaging", "SystemState")
    SystemState.objects.get_or_create(pk=1)


def remove_system_state(apps, schema_editor):
    SystemState = apps.get_model("messaging", "SystemState")
    SystemState.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [("messaging", "0001_initial")]

    operations = [migrations.RunPython(create_system_state, remove_system_state)]

