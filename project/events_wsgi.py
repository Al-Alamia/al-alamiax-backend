import os

import django
from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
django.setup()
settings.ROOT_URLCONF = "project.events_urls"

application = get_wsgi_application()
