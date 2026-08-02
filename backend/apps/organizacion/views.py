"""Vistas de la API de organización (Parte C del encargo de membresías).

``GET /api/sedes/`` es de SOLO LECTURA (ver decisión en el docstring de
``SedeListView``); no expone ``permiso_requerido`` -- el frontend lo
necesita para saber qué sedes tiene disponibles ANTES de poder decidir en
cuál trabajar, así que exigir un permiso de negocio (p. ej.
``clientes.ver``) sería arbitrario y dejaría sin sedes a un usuario cuyo rol
no tenga ese permiso concreto pero sí necesite saber dónde está. Basta con
estar autenticado (``IsAuthenticated``, permiso por defecto del proyecto);
RLS ya acota el resultado a las sedes del tenant del usuario.
"""
from rest_framework.generics import ListAPIView

from .models import Sede
from .serializers import SedeSerializer


class SedeListView(ListAPIView):
    """``GET /api/sedes/``: lista las sedes del gimnasio del usuario
    autenticado (RLS ya las acota; no hace falta filtrar por tenant aquí).

    Decisión: solo lectura, no CRUD. La app expone ``config.sedes`` como
    permiso reservado para cuando exista gestión (crear/editar/desactivar
    sedes), pero eso no forma parte de este encargo -- lo que el frontend
    necesita ahora mismo es dejar de asumir "la primera sede del usuario" y
    poder listar de verdad. Si más adelante se agrega CRUD, este mismo
    ``ListAPIView`` puede convertirse en un ``ModelViewSet`` con
    ``permisos_por_accion`` subiendo a ``config.sedes`` en create/update/destroy,
    igual que en ``ClienteViewSet``/``VentaViewSet``.
    """

    serializer_class = SedeSerializer

    def get_queryset(self):
        return Sede.objects.order_by('nombre')
