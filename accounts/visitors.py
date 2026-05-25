"""Anonymous visitor tracking (no signup required)."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.utils import timezone

if TYPE_CHECKING:
    from django.http import HttpRequest

    from accounts.models import GuestVisitor, User

logger = logging.getLogger("accounts")

VISITOR_HEADER = "HTTP_X_VISITOR_ID"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


@dataclass
class RequestActor:
    user: User | None
    guest: GuestVisitor | None

    @property
    def is_registered(self) -> bool:
        return self.user is not None

    def owner_label(self) -> str:
        if self.user:
            return self.user.email
        if self.guest:
            return f"visitor:{self.guest.visitor_key[:8]}"
        return "anonymous"


def get_client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _lookup_geo(ip: str | None) -> dict[str, str]:
    if not ip or ip in {"127.0.0.1", "::1"}:
        return {}
    if ip.startswith(("10.", "192.168.")):
        return {}
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            if 16 <= second <= 31:
                return {}
        except ValueError:
            pass
    try:
        req = Request(
            f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city",
            headers={"User-Agent": "MaishaChat/1.0"},
        )
        with urlopen(req, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") != "success":
            return {}
        return {
            "country": data.get("country") or "",
            "region": data.get("regionName") or "",
            "city": data.get("city") or "",
        }
    except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        logger.debug("Geo lookup failed for %s", ip, exc_info=True)
        return {}


def resolve_actor(request: HttpRequest) -> RequestActor:
    from accounts.models import GuestVisitor

    user = request.user if getattr(request.user, "is_authenticated", False) else None
    guest: GuestVisitor | None = None

    raw = (request.META.get(VISITOR_HEADER) or "").strip()
    if raw and UUID_RE.match(raw):
        ip = get_client_ip(request)
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:512]
        guest, created = GuestVisitor.objects.get_or_create(
            visitor_key=raw,
            defaults={
                "first_ip": ip,
                "last_ip": ip,
                "user_agent": ua,
            },
        )
        changed: list[str] = []
        if not created:
            guest.last_seen = timezone.now()
            guest.visit_count += 1
            changed.extend(["last_seen", "visit_count"])
            if ip and guest.last_ip != ip:
                guest.last_ip = ip
                changed.append("last_ip")
            if ua and guest.user_agent != ua:
                guest.user_agent = ua
                changed.append("user_agent")

        if created or not guest.country:
            geo = _lookup_geo(ip)
            for field in ("country", "region", "city"):
                val = geo.get(field, "")
                if val and getattr(guest, field) != val:
                    setattr(guest, field, val)
                    if field not in changed:
                        changed.append(field)

        if user and guest.linked_user_id != user.id:
            guest.linked_user = user
            changed.append("linked_user")

        if changed:
            guest.save(update_fields=changed)

    return RequestActor(user=user, guest=guest)


def conversation_owner_q(actor: RequestActor) -> dict:
    if actor.user:
        return {"user": actor.user}
    if actor.guest:
        return {"guest": actor.guest}
    raise ValueError("No user or guest on request")


def require_actor(actor: RequestActor) -> None:
    if not actor.user and not actor.guest:
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Missing visitor id. Send X-Visitor-Id header.")


def actor_owner_kwargs(actor: RequestActor) -> dict:
    if actor.user:
        return {"user": actor.user, "guest": None}
    return {"user": None, "guest": actor.guest}


def merge_guest_into_user(guest: GuestVisitor, user: User) -> None:
    """Attach anonymous activity to a registered account on login/signup."""
    from arena.models import ArenaBattle
    from chat.models import Conversation
    from rlhf.models import MessageFeedback, RegenerationPair

    guest.linked_user = user
    guest.save(update_fields=["linked_user"])
    Conversation.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
    ArenaBattle.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
    MessageFeedback.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
    RegenerationPair.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )


def actor_owner_kwargs(actor: RequestActor) -> dict:
    if actor.user:
        return {"user": actor.user, "guest": None}
    return {"user": None, "guest": actor.guest}


def merge_guest_into_user(guest: GuestVisitor, user: User) -> None:
    """Attach anonymous activity to a registered account on login/signup."""
    from arena.models import ArenaBattle
    from chat.models import Conversation
    from rlhf.models import MessageFeedback, RegenerationPair

    guest.linked_user = user
    guest.save(update_fields=["linked_user"])
    Conversation.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
    ArenaBattle.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
    MessageFeedback.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
    RegenerationPair.objects.filter(guest=guest, user__isnull=True).update(
        user=user, guest=None
    )
