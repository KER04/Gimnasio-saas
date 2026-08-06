"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.autenticacion.urls')),
    path('api/', include('apps.ventas.urls')),
    # Parte B (RF-03): /api/clientes/... -- movido por completo desde
    # apps.ventas.urls (Parte B1), una sola implementación.
    path('api/', include('apps.clientes.urls')),
    # Endpoints de membresías (asignación directa, renovar, cancelar,
    # tablero de vencimientos): /api/membresias/...
    path('api/', include('apps.membresias.urls')),
    # /api/sedes/ (solo lectura).
    path('api/', include('apps.organizacion.urls')),
    # /api/asistencias/... (RF-15, sin biometría: el lector aún no llegó).
    path('api/', include('apps.asistencia.urls')),
    # /api/productos/, /api/categorias-producto/ y /api/movimientos-inventario/.
    path('api/', include('apps.inventario.urls')),
    # /api/reportes/... (RF-08): caja, ventas y productos. Solo agregados.
    path('api/', include('apps.reportes.urls')),
    # Panel del PROVEEDOR (no de un gimnasio): /api/plataforma/...
    # Identidad propia (`usuarios_plataforma`) y sin tenant. Ver
    # TENANT_EXEMPT_PATHS y apps/plataforma/auth.py.
    path('api/plataforma/', include('apps.plataforma.urls')),
]
