"""Rutas del panel del proveedor, todas bajo ``/api/plataforma/``.

El prefijo importa: es el que ``TENANT_EXEMPT_PATHS`` usa para NO resolver
tenant en estas peticiones, y el que el frontend usa para mandar el token del
panel en vez del token del gimnasio.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CambiarPasswordPlataformaView,
    LoginPlataformaView,
    RefrescoPlataformaView,
    TenantViewSet,
    YoPlataformaView,
)

app_name = 'plataforma'

router = DefaultRouter()
router.register('tenants', TenantViewSet, basename='tenant')

urlpatterns = [
    path('login/', LoginPlataformaView.as_view(), name='login'),
    path('refresh/', RefrescoPlataformaView.as_view(), name='refresh'),
    path('me/', YoPlataformaView.as_view(), name='me'),
    path('cambiar-password/', CambiarPasswordPlataformaView.as_view(), name='cambiar-password'),
    path('', include(router.urls)),
]
