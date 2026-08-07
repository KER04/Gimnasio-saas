"""URLs de entrenamiento (RF-12). Se incluye en ``config/urls.py`` bajo el
prefijo ``api/``: ``/api/ejercicios/``, ``/api/rutinas/`` y
``/api/fichas-medidas/``.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EjercicioViewSet, FichaMedidasViewSet, GrupoMuscularListView, RutinaViewSet

router = DefaultRouter()
router.register('ejercicios', EjercicioViewSet, basename='ejercicio')
router.register('rutinas', RutinaViewSet, basename='rutina')
router.register('fichas-medidas', FichaMedidasViewSet, basename='ficha-medidas')

urlpatterns = [
    path('grupos-musculares/', GrupoMuscularListView.as_view(), name='grupos-musculares'),
    path('', include(router.urls)),
]
