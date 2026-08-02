"""URLs de la API de membresías (Parte A del encargo de membresías). Se
incluye en ``config/urls.py`` bajo el prefijo ``api/``, quedando en
``/api/membresias/...``.
"""
from rest_framework.routers import DefaultRouter

from .views import MembresiaViewSet

router = DefaultRouter()
router.register('membresias', MembresiaViewSet, basename='membresia')

urlpatterns = router.urls
