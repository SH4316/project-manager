from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import ApiToken

from ..forms import ProfileForm, TokenForm


@login_required
def profile(request):
    u = request.user
    form = ProfileForm(
        request.POST or None,
        initial={"display_name": u.display_name, "discord_user_id": u.discord_user_id or ""},
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        discord = (d["discord_user_id"] or "").strip()
        if discord and not discord.isdigit():
            form.add_error("discord_user_id", "숫자만 입력하세요.")
        else:
            u.display_name = d["display_name"]
            u.discord_user_id = discord or None
            u.save(update_fields=["display_name", "discord_user_id"])
            messages.success(request, "프로필을 저장했습니다.")
            return redirect("profile")
    return render(request, "settings/profile.html", {"form": form})


@login_required
def tokens(request):
    if request.method == "POST":
        form = TokenForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            _, raw = ApiToken.issue(request.user, d["name"], d["scope"])
            request.session["new_token"] = raw
            return redirect("tokens")
    else:
        form = TokenForm()
    return render(
        request,
        "settings/tokens.html",
        {
            "form": form,
            "tokens": request.user.tokens.all(),
            "new_token": request.session.pop("new_token", None),
        },
    )


@login_required
@require_POST
def token_revoke(request, token_id):
    token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
    token.revoke()
    return redirect("tokens")
