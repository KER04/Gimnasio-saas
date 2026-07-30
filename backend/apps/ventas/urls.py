"""URLs de ventas/POS (Parte D). Se incluye en ``config/urls.py`` bajo el
prefijo ``api/``, de modo que quedan exactamente en las rutas que pide el
encargo: ``/api/ventas/...``, ``/api/productos/``, ``/api/planes/``,
``/api/clientes/``.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ClienteListView, PlanListView, ProductoListView, VentaViewSet

router = DefaultRouter()
router.register('ventas', VentaViewSet, basename='venta')

urlpatterns = [
    path('productos/', ProductoListView.as_view(), name='productos-list'),
    path('planes/', PlanListView.as_view(), name='planes-list'),
    path('clientes/', ClienteListView.as_view(), name='clientes-list'),
    path('', include(router.urls)),
]
