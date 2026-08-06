"""URLs de ventas/POS (Parte D). Se incluye en ``config/urls.py`` bajo el
prefijo ``api/``, de modo que quedan exactamente en las rutas que pide el
encargo: ``/api/ventas/...``, ``/api/productos/``.

``/api/clientes/`` YA NO se registra aquí (Parte B1 del encargo de
clientes, RF-03): se trasladó por completo a ``apps.clientes.urls``, que
``config/urls.py`` incluye por separado bajo el mismo prefijo ``api/``. El
buscador del POS sigue pegándole a la misma URL de siempre; solo cambió
dónde vive la implementación.

``/api/planes/`` TAMPOCO se registra ya aquí (pantalla "Gestión de
Membresías"): se trasladó a ``apps.membresias.urls`` al convertirse de
listado de solo lectura en CRUD completo, junto al modelo ``Plan``. Sigue en
la misma URL, mismo método (``GET``) y mismo permiso (``membresias.gestionar``)
para quien ya lo consumía -- el POS no nota el cambio.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import VentaViewSet
from .views_caja import (
    CategoriaGastoListView,
    CategoriaIngresoListView,
    GastoViewSet,
    IngresoOtroViewSet,
)

router = DefaultRouter()
router.register('ventas', VentaViewSet, basename='venta')
# Movimientos de caja sin venta detrás (RF-24 y RF-07). Comparten app con las
# ventas porque comparten tablas y el corte de caja los suma juntos.
router.register('gastos', GastoViewSet, basename='gasto')
router.register('ingresos', IngresoOtroViewSet, basename='ingreso')

urlpatterns = [
    path('categorias-gasto/', CategoriaGastoListView.as_view(), name='categorias-gasto'),
    path('categorias-ingreso/', CategoriaIngresoListView.as_view(), name='categorias-ingreso'),
    path('', include(router.urls)),
]
