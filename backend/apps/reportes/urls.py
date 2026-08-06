"""URLs de informes. Se incluye en ``config/urls.py`` bajo el prefijo
``api/``, quedando en ``/api/reportes/...``.

No usa router: no son recursos REST sino agregados de solo lectura, cada uno
con su propia forma de respuesta.
"""
from django.urls import path

from .views import (
    ReporteCajaView,
    ReporteCarteraView,
    ReporteProductosView,
    ReporteUtilidadView,
    ReporteVentasView,
)

urlpatterns = [
    path('reportes/ventas/', ReporteVentasView.as_view(), name='reporte-ventas'),
    path('reportes/caja/', ReporteCajaView.as_view(), name='reporte-caja'),
    path('reportes/cartera/', ReporteCarteraView.as_view(), name='reporte-cartera'),
    path('reportes/productos/', ReporteProductosView.as_view(), name='reporte-productos'),
    # Márgenes: exige `costos.ver`, no `reportes.ver` (ver el docstring).
    path('reportes/utilidad/', ReporteUtilidadView.as_view(), name='reporte-utilidad'),
]
