import os
import re

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myProject.settings")
django.setup()

from django.test import Client

c = Client(enforce_csrf_checks=True)
r = c.get("/oversight/login/", HTTP_HOST="127.0.0.1")
html = r.content.decode()
old_token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
c.cookies["csrftoken"] = "abcdefghijklmnopqrstuvwxyz012345"
r2 = c.post(
    "/oversight/login/",
    {"username": "Julia", "password": "wrong", "csrfmiddlewaretoken": old_token},
    HTTP_HOST="127.0.0.1",
)
body = r2.content.decode()
print("stale POST status:", r2.status_code)
print("friendly message:", "Session expired" in body)
