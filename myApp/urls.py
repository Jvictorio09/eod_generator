from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/generate-eod/", views.generate_eod_report, name="generate_eod_report"),
]
