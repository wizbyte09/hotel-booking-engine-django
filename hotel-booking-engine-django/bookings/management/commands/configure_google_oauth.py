import os

from django.core.management.base import BaseCommand, CommandError
from django.contrib.sites.models import Site
from allauth.socialaccount.models import SocialApp


class Command(BaseCommand):
    help = 'Configure the Google OAuth SocialApp from environment variables.'

    def handle(self, *args, **options):
        client_id = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
        secret = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')
        if not client_id or not secret:
            raise CommandError('Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET first.')

        site = Site.objects.get_or_create(
            id=1,
            defaults={'domain': '127.0.0.1:8000', 'name': 'Lumen House Local'},
        )[0]
        site.domain = os.environ.get('OAUTH_SITE_DOMAIN', site.domain)
        site.name = os.environ.get('OAUTH_SITE_NAME', site.name)
        site.save(update_fields=['domain', 'name'])

        app, _ = SocialApp.objects.update_or_create(
            provider='google',
            defaults={'name': 'Google', 'client_id': client_id, 'secret': secret},
        )
        app.sites.set([site])
        self.stdout.write(self.style.SUCCESS(f'Google OAuth configured for {site.domain}.'))
