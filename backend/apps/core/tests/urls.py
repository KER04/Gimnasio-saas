"""URLconf mínimo, usado SOLO por apps/core/tests/test_middleware.py (vía
``override_settings(ROOT_URLCONF=...)``) para poder inspeccionar, desde una
vista real, qué dejó ``TenantMiddleware`` en ``request.tenant``/
``request.tenant_id``. No se registra en ``config/urls.py``: no debe existir
fuera de las pruebas.
"""
from django.http import JsonResponse
from django.urls import path


def ping(request):
    tenant = getattr(request, 'tenant', None)
    return JsonResponse({
        'tenant_id': getattr(request, 'tenant_id', None),
        'subdominio': tenant.subdominio if tenant is not None else None,
    })


urlpatterns = [
    path('ping/', ping, name='ping'),
]
