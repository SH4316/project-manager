from django.db import models


class IntegrationStatus(models.Model):
    name = models.CharField(max_length=20, unique=True)
    last_run_at = models.DateTimeField()
    ok = models.BooleanField()
    detail = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name}: {'ok' if self.ok else 'fail'}"
