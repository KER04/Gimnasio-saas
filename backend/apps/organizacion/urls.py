"""URLs de la API de organización (Parte C del encargo de membresías). Se
incluye en ``config/urls.py`` bajo el prefijo ``api/``, quedando en
``/api/sedes/``.
"""
from django.urls import path

from .views import SedeListView

urlpatterns = [
    path('sedes/', SedeListView.as_view(), name='sedes-list'),
]
