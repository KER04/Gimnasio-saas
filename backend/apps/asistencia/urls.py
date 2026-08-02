"""URLs de la API de asistencia (RF-15). Se incluye en ``config/urls.py``
bajo el prefijo ``api/``, quedando en ``/api/asistencias/...``.
"""
from rest_framework.routers import DefaultRouter

from .views import AsistenciaViewSet

router = DefaultRouter()
router.register('asistencias', AsistenciaViewSet, basename='asistencia')

urlpatterns = router.urls
