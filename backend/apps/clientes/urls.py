"""URLs de la API de clientes (Parte B del encargo, RF-03). Se incluye en
``config/urls.py`` bajo el prefijo ``api/``, quedando en
``/api/clientes/...`` -- exactamente donde vivía antes el endpoint de apoyo
del POS (ahora movido aquí por completo, ver Parte B1 / apps/ventas/urls.py).
"""
from rest_framework.routers import DefaultRouter

from .views import ClienteViewSet

router = DefaultRouter()
router.register('clientes', ClienteViewSet, basename='cliente')

urlpatterns = router.urls
