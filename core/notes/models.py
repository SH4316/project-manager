from django.conf import settings
from django.db import models

from common.dates import today_kst


class MeetingNote(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="notes")
    # 프로젝트가 없으면 "팀 공통" 회의록이다.
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="notes"
    )
    title = models.CharField("제목", max_length=200, default="제목 없는 회의록")
    body_md = models.TextField("본문", blank=True)
    # 회의를 한 날. 사용자가 고친다. created_at(기록 시각)과 다르다.
    created_on = models.DateField("생성일", default=today_kst)
    version = models.PositiveIntegerField(default=1)
    # related_name="notes"는 Task.notes(진행 메모 텍스트 필드)와 이름이 부딪힌다.
    tasks = models.ManyToManyField("tasks.Task", blank=True, related_name="meeting_notes")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_on", "-id"]

    def __str__(self):
        return self.title
