"""URLs de la API de membresías (Parte A del encargo de membresías). Se
incluye en ``config/urls.py`` bajo el prefijo ``api/``, quedando en
``/api/membresias/...`` y ``/api/planes/...``.

``/api/planes/`` se trasladó aquí desde ``apps.ventas.urls`` al convertirse
de listado de solo lectura en CRUD completo (pantalla "Gestión de
Membresías"): tiene más sentido junto al modelo ``Plan`` que vive en esta
app. Ver la nota en ``apps.ventas.urls`` sobre compatibilidad con el POS.
"""
from rest_framework.routers import DefaultRouter

from .views import MembresiaViewSet, PlanViewSet

router = DefaultRouter()
router.register('membresias', MembresiaViewSet, basename='membresia')
router.register('planes', PlanViewSet, basename='plan')

urlpatterns = router.urls
