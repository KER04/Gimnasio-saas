"""URLs de la API de organización. Se incluye en ``config/urls.py`` bajo el
prefijo ``api/``, quedando en ``/api/sedes/``, ``/api/roles/`` y
``/api/usuarios/``.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import RolListView, SedeListView, UsuarioViewSet

router = DefaultRouter()
router.register('usuarios', UsuarioViewSet, basename='usuario')

urlpatterns = [
    path('sedes/', SedeListView.as_view(), name='sedes-list'),
    path('roles/', RolListView.as_view(), name='roles-list'),
    path('', include(router.urls)),
]
