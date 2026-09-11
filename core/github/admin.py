from django.contrib import admin

from .models import GitHubIdentity, GitHubInstallation, RepoConnection


@admin.register(GitHubInstallation)
class InstallationAdmin(admin.ModelAdmin):
    list_display = ["account_login", "installation_id", "org", "installed_at", "suspended_at"]


@admin.register(GitHubIdentity)
class IdentityAdmin(admin.ModelAdmin):
    # 토큰 필드는 암호문이라도 화면에 띄우지 않는다.
    list_display = ["login", "user", "repos_checked_at", "connected_at"]
    fields = ["user", "github_id", "login", "repos", "repos_checked_at"]


@admin.register(RepoConnection)
class RepoConnectionAdmin(admin.ModelAdmin):
    list_display = ["full_name", "project", "auto_import", "last_event_at"]
