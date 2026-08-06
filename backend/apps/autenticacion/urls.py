from django.urls import path

from .views import (
    CambiarPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    RegisterView,
)

app_name = 'autenticacion'
urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    # RefreshView propia, no la de simplejwt: su serializer consulta `usuarios`
    # (tabla con RLS) para comprobar que el usuario sigue activo, y necesita el
    # tenant fijado antes. Ver el docstring de la vista.
    path('refresh/', RefreshView.as_view(), name='refresh'),
    path('register/', RegisterView.as_view(), name='register'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('cambiar-password/', CambiarPasswordView.as_view(), name='cambiar-password'),
]
