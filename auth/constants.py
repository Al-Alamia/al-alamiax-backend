from django.conf import settings


AUTH_COOKIE = settings.SIMPLE_JWT["AUTH_COOKIE"]
SESSION_ID = "sessionid"
CSRF_TOKEN = "csrftoken"
EXPIRE = "expire"
REFRESH_COOKIE = "refreshtoken"