"""URLs de la API de inventario. Se incluye en ``config/urls.py`` bajo el
prefijo ``api/``, quedando en ``/api/productos/``,
``/api/categorias-producto/`` y ``/api/movimientos-inventario/``.

``/api/productos/`` se trasladó aquí desde ``apps.ventas.urls`` al convertirse
de listado de solo lectura en CRUD completo: tiene más sentido junto al
modelo ``Producto``, que vive en esta app. Misma URL, mismo parámetro
``sede_id`` y mismo permiso de lectura, así que el buscador del POS no nota
el cambio.
"""
from rest_framework.routers import DefaultRouter

from .views import CategoriaProductoViewSet, MovimientoInventarioViewSet, ProductoViewSet

router = DefaultRouter()
router.register('productos', ProductoViewSet, basename='producto')
router.register('categorias-producto', CategoriaProductoViewSet, basename='categoria-producto')
router.register('movimientos-inventario', MovimientoInventarioViewSet, basename='movimiento-inventario')

urlpatterns = router.urls
