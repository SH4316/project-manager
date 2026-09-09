from django import forms
from django.contrib.auth.forms import UserCreationForm

from accounts.models import User
from projects.models import Project
from tasks.models import Link

PRIORITY_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]


class SignupForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "display_name")
        labels = {"username": "아이디", "display_name": "표시 이름"}


class TeamForm(forms.Form):
    name = forms.CharField(label="팀 이름", max_length=100)
    purpose = forms.CharField(label="목적 한 줄", max_length=200, required=False)


class InviteForm(forms.Form):
    days = forms.IntegerField(label="만료(일)", min_value=1, max_value=90, initial=7)


class ProjectForm(forms.Form):
    """프로젝트 모달. 관리자는 체크 칩, 상태는 카드형 라디오로 템플릿이 직접 그린다."""

    # 빈 이름 검사는 services.create_project/update_project가 한다(업무 규칙은 services에만).
    name = forms.CharField(label="이름", max_length=100, required=False)
    purpose = forms.CharField(
        label="목적", max_length=200, required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    owners = forms.ModelMultipleChoiceField(
        label="관리자", queryset=User.objects.none(), required=False
    )
    status = forms.ChoiceField(label="상태", choices=Project.STATUSES, initial="preparing")
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owners"].queryset = team.members.filter(is_active=True).order_by(
            "display_name"
        )


class TaskForm(forms.Form):
    """전체 수정 화면(/tasks/{id}/edit). 담당자·프로젝트·기한 미정 사유는 여기서만 바꾼다."""

    project = forms.ModelChoiceField(label="프로젝트", queryset=Project.objects.none())
    title = forms.CharField(label="제목", max_length=200)
    assignee = forms.ModelChoiceField(label="담당자", queryset=User.objects.none())
    priority = forms.TypedChoiceField(
        label="중요도", choices=PRIORITY_CHOICES, coerce=int, initial=5
    )
    due_date = forms.DateField(
        label="목표 기한", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    no_due_reason = forms.CharField(label="기한 미정 사유", max_length=200, required=False)
    description = forms.CharField(
        label="설명", required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    done_when = forms.CharField(label="완료 조건", max_length=300, required=False)
    next_action = forms.CharField(label="다음 행동", max_length=200, required=False)
    version = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(
            team=team, is_archived=False
        ).order_by("name")
        self.fields["assignee"].queryset = team.members.filter(is_active=True).order_by(
            "display_name"
        )


class TaskInlineForm(forms.Form):
    """프로젝트 화면의 태스크 만들기 인라인 폼."""

    title = forms.CharField(max_length=200)
    assignee = forms.ModelChoiceField(queryset=User.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    idem = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, team, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = team.members.filter(is_active=True).order_by(
            "display_name"
        )


class QuickTaskForm(forms.Form):
    """오늘 화면의 빠른 추가: 제목·프로젝트·중요도·기한(없으면 사유). 담당자는 본인."""

    title = forms.CharField(max_length=200)
    project = forms.ModelChoiceField(queryset=Project.objects.none())
    priority = forms.TypedChoiceField(choices=PRIORITY_CHOICES, coerce=int, initial=5)
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    no_due_reason = forms.CharField(max_length=200, required=False)
    idem = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        from teams.services import teams_of

        self.fields["project"].queryset = (
            Project.objects.filter(team__in=teams_of(user), is_archived=False)
            .select_related("team")
            .order_by("team__name", "name")
        )


class LinkForm(forms.Form):
    title = forms.CharField(label="제목", max_length=100)
    url = forms.URLField(label="URL", max_length=500)
    kind = forms.ChoiceField(label="종류", choices=Link.KINDS, initial="doc")


class ProfileForm(forms.Form):
    display_name = forms.CharField(label="표시 이름", max_length=50)
    discord_user_id = forms.CharField(
        label="Discord 사용자 ID (숫자)", max_length=32, required=False
    )


class TokenForm(forms.Form):
    name = forms.CharField(label="이름", max_length=50)
    scope = forms.ChoiceField(
        label="범위", choices=[("read", "읽기"), ("write", "읽기·쓰기")], initial="read"
    )
