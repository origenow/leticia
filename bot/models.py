"""Models mirror the Supabase `leticia` schema.

Source of truth is `supabase/schema.sql`. Django never creates/alters these tables —
all models are `managed = False`. The schema is selected via Postgres `search_path`
set in settings.DATABASES (-c search_path=leticia,public).
"""
from django.db import models


class Lead(models.Model):
    phone = models.CharField(max_length=32, unique=True)
    display_name = models.CharField(max_length=200, blank=True, default="")
    source = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    autonomy_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads"
        managed = False

    def __str__(self) -> str:
        return f"{self.display_name or self.phone}"


class Conversation(models.Model):
    STATUS_CHOICES = [
        ("active", "active"),
        ("paused", "paused"),
        ("escalated", "escalated"),
        ("closed", "closed"),
    ]
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="conversations")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "conversations"
        managed = False


class Message(models.Model):
    DIRECTION_CHOICES = [("inbound", "inbound"), ("outbound", "outbound")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    body = models.TextField()
    evolution_message_id = models.CharField(max_length=128, blank=True, default="")
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        managed = False


class OptOut(models.Model):
    phone = models.CharField(max_length=32, unique=True)
    reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "opt_outs"
        managed = False


class Escalation(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)
    trigger = models.CharField(max_length=64)
    context = models.TextField(blank=True, default="")
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "escalations"
        managed = False


class CommandLog(models.Model):
    """Audit trail for Slack-triggered commands."""
    slack_user_id = models.CharField(max_length=32)
    slack_user_name = models.CharField(max_length=128, blank=True, default="")
    command = models.CharField(max_length=64)
    args = models.TextField(blank=True, default="")
    result = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "command_log"
        managed = False
