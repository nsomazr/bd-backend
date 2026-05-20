"""Idempotently create or refresh the platform admin account.

Defaults match the project owner's account; both can be overridden via
``ADMIN_EMAIL`` / ``ADMIN_PASSWORD`` environment variables or via the CLI
flags ``--email`` / ``--password``.
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand

from accounts.models import User

DEFAULT_EMAIL = "happiness@maishachat.or.tz"
DEFAULT_PASSWORD = "@happy@maisha"
DEFAULT_NAME = "Happiness"


class Command(BaseCommand):
    help = "Create or refresh the admin (is_staff + is_superuser) account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default=os.getenv("ADMIN_EMAIL", DEFAULT_EMAIL),
        )
        parser.add_argument(
            "--password",
            default=os.getenv("ADMIN_PASSWORD", DEFAULT_PASSWORD),
        )
        parser.add_argument(
            "--name",
            default=os.getenv("ADMIN_NAME", DEFAULT_NAME),
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="If the user already exists, reset its password to the supplied value.",
        )

    def handle(self, *args, **options):
        email = (options["email"] or "").strip().lower()
        password = options["password"]
        name = options["name"]
        reset = options["reset_password"]

        if not email or not password:
            self.stderr.write(self.style.ERROR("email and password are required"))
            return

        user, created = User.objects.get_or_create(
            email=email,
            defaults={"name": name, "is_staff": True, "is_superuser": True, "is_active": True},
        )

        changed = False
        if not user.is_staff:
            user.is_staff = True
            changed = True
        if not user.is_superuser:
            user.is_superuser = True
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if name and user.name != name:
            user.name = name
            changed = True

        if created or reset:
            user.set_password(password)
            changed = True

        if changed:
            user.save()

        verb = "Created" if created else ("Updated" if changed else "Verified")
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} admin account: {user.email} (is_staff={user.is_staff}, "
                f"is_superuser={user.is_superuser})"
            )
        )
