import os
import re
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myProject.settings")
django.setup()

from django.test import Client

c = Client(enforce_csrf_checks=True)
r = c.get("/login/", HTTP_HOST="127.0.0.1")
html = r.content.decode()
m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
form_token = m.group(1) if m else ""
r2 = c.post(
    "/login/",
    {"username": "admin", "password": "wrong", "csrfmiddlewaretoken": form_token},
    HTTP_HOST="127.0.0.1",
)
print("GET", r.status_code, "csrf cookie", bool(r.cookies.get("csrftoken")))
print("POST", r2.status_code, "(403 = CSRF broken)")
