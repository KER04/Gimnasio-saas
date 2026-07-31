"""URLs de ventas/POS (Parte D). Se incluye en ``config/urls.py`` bajo el
prefijo ``api/``, de modo que quedan exactamente en las rutas que pide el
encargo: ``/api/ventas/...``, ``/api/productos/``, ``/api/planes/``.

``/api/clientes/`` YA NO se registra aquí (Parte B1 del encargo de
clientes, RF-03): se trasladó por completo a ``apps.clientes.urls``, que
``config/urls.py`` incluye por separado bajo el mismo prefijo ``api/``. El
buscador del POS sigue pegándole a la misma URL de siempre; solo cambió
dónde vive la implementación.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PlanListView, ProductoListView, VentaViewSet

router = DefaultRouter()
router.register('ventas', VentaViewSet, basename='venta')

urlpatterns = [
    path('productos/', ProductoListView.as_view(), name='productos-list'),
    path('planes/', PlanListView.as_view(), name='planes-list'),
    path('', include(router.urls)),
]
