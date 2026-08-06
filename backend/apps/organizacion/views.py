"""Vistas de la API de organización: sedes, roles y usuarios del gimnasio.

``GET /api/sedes/`` es de SOLO LECTURA (ver el docstring de ``SedeListView``).
``/api/usuarios/`` sí es gestión completa, detrás de ``config.usuarios``.
"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.core.permissions import TienePermiso
from apps.plataforma.aprovisionamiento import generar_password

from .models import Rol, Sede, UsuarioSede
from .serializers import (
    RolSerializer,
    SedeSerializer,
    UsuarioActualizarSerializer,
    UsuarioCrearSerializer,
    UsuarioSerializer,
    hay_otro_administrador,
)

Usuario = get_user_model()


class SedeListView(ListAPIView):
    """``GET /api/sedes/``: lista las sedes del gimnasio del usuario
    autenticado (RLS ya las acota; no hace falta filtrar por tenant aquí).

    Decisión: solo lectura, no CRUD. La app expone ``config.sedes`` como
    permiso reservado para cuando exista gestión (crear/editar/desactivar
    sedes), pero eso no forma parte de este encargo -- lo que el frontend
    necesita ahora mismo es dejar de asumir "la primera sede del usuario" y
    poder listar de verdad.
    """

    serializer_class = SedeSerializer

    def get_queryset(self):
        return Sede.objects.order_by('nombre')


class RolListView(ListAPIView):
    """``GET /api/roles/`` (``config.usuarios``): los roles disponibles al
    crear o editar un usuario.

    Exige el permiso de administración porque saber qué roles existen solo
    hace falta para asignarlos.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'config.usuarios'
    serializer_class = RolSerializer

    def get_queryset(self):
        return Rol.objects.filter(activo=True).prefetch_related('roles_permisos').order_by('nombre')


class UsuarioViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """``/api/usuarios/`` (``config.usuarios``): el personal del gimnasio.

    ## Por qué no hay borrado

    ``Venta``, ``Pago``, ``IngresoOtro``, ``Gasto`` y los movimientos de
    inventario apuntan al usuario con ``PROTECT``: en cuanto alguien cobra
    una venta, su fila ya no se puede borrar sin romper el histórico. Y así
    debe ser -- un recibo tiene que poder decir quién lo hizo aunque esa
    persona ya no trabaje allí. Dar de baja es ``activo=False``.

    ## Las guardas

    Tres comprobaciones impiden el accidente que dejaría al gimnasio sin
    poder administrarse (ver ``serializers.hay_otro_administrador``):
    nadie se desactiva a sí mismo, nadie se cambia su propio rol, y no se
    puede dejar el gimnasio sin ningún administrador activo. Sin ellas, la
    única salida sería llamar al proveedor.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'config.usuarios'

    def get_queryset(self):
        # RLS ya acota a los usuarios del tenant: no hace falta filtrar aquí.
        return (
            Usuario.objects
            .select_related('rol')
            .prefetch_related('usuarios_sedes__sede')
            .order_by('-activo', 'nombre')
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return UsuarioCrearSerializer
        if self.action in ('update', 'partial_update'):
            return UsuarioActualizarSerializer
        return UsuarioSerializer

    def list(self, request, *args, **kwargs):
        """Por defecto solo los activos. ``?incluir_inactivos=1`` los trae
        todos: es el único sitio desde el que se puede reactivar a alguien."""
        qs = self.filter_queryset(self.get_queryset())
        if request.query_params.get('incluir_inactivos', '') not in ('1', 'true', 'True'):
            qs = qs.filter(activo=True)

        pagina = self.paginate_queryset(qs)
        if pagina is not None:
            return self.get_paginated_response(UsuarioSerializer(pagina, many=True).data)
        return Response(UsuarioSerializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        """Crea el usuario y devuelve su contraseña UNA sola vez.

        No se guarda en claro en ninguna parte ni se puede volver a
        consultar: si se pierde, se restablece.
        """
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data
        sedes = datos.pop('sedes', [])

        password = generar_password()

        try:
            with transaction.atomic():
                usuario = Usuario.objects.create_user(
                    correo=datos['correo'],
                    nombre=datos['nombre'],
                    # El tenant sale del middleware, NUNCA del cuerpo de la
                    # petición: si viniera de fuera, un administrador podría
                    # crear usuarios dentro de otro gimnasio.
                    tenant=request.tenant,
                    rol=datos['rol'],
                    password=password,
                    telefono=datos.get('telefono'),
                )
                self._fijar_sedes(usuario, sedes)
        except IntegrityError:
            # Carrera: otro alta se quedó con el correo entre la validación y
            # el INSERT. La restricción única de la base es la que decide.
            return Response(
                {'correo': ['Ya hay un usuario con ese correo en este gimnasio.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                **UsuarioSerializer(usuario).data,
                'password': password,
            },
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        """Siempre parcial: el panel manda solo lo que cambió, y exigir la
        ficha entera invitaría a pisar campos sin querer."""
        usuario = self.get_object()
        entrada = self.get_serializer(usuario, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)

        sedes = entrada.validated_data.pop('sedes', None)
        entrada.save()
        if sedes is not None:
            self._fijar_sedes(usuario, sedes)

        usuario.refresh_from_db()
        return Response(UsuarioSerializer(usuario).data)

    def _fijar_sedes(self, usuario, sedes):
        """Deja al usuario asignado EXACTAMENTE a las sedes indicadas.

        Se borra y se vuelve a crear en vez de calcular diferencias: la tabla
        no tiene más datos que la pareja y la fecha de asignación, así que no
        se pierde nada y el código no tiene que razonar sobre altas y bajas.
        """
        UsuarioSede.objects.filter(usuario=usuario).delete()
        UsuarioSede.objects.bulk_create([
            UsuarioSede(usuario=usuario, sede=sede, tenant_id=usuario.tenant_id)
            for sede in sedes
        ])

    @action(detail=True, methods=['post'])
    def desactivar(self, request, pk=None):
        """Quita el acceso sin borrar nada. Su histórico de ventas y cobros
        sigue intacto y sigue diciendo quién hizo cada cosa."""
        usuario = self.get_object()

        if usuario.pk == request.user.pk:
            return Response(
                {'detail': 'No puedes desactivarte a ti mismo: te quedarías fuera del gimnasio.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        es_admin = usuario.rol.roles_permisos.filter(permiso__codigo='config.usuarios').exists()
        if es_admin and not hay_otro_administrador(usuario):
            return Response(
                {
                    'detail': (
                        'Es el único administrador activo del gimnasio. Si lo desactivas, '
                        'nadie podrá gestionar usuarios ni restablecer contraseñas. '
                        'Nombra antes a otro administrador.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        usuario.activo = False
        usuario.save(update_fields=['activo'])
        return Response(UsuarioSerializer(usuario).data)

    @action(detail=True, methods=['post'])
    def activar(self, request, pk=None):
        usuario = self.get_object()
        usuario.activo = True
        usuario.save(update_fields=['activo'])
        return Response(UsuarioSerializer(usuario).data)

    @action(detail=True, methods=['post'], url_path='restablecer-password')
    def restablecer_password(self, request, pk=None):
        """Genera una contraseña nueva y la devuelve UNA vez.

        Es lo que resuelve la llamada más frecuente de cualquier gimnasio:
        "no me acuerdo de mi contraseña". Sin esto había que molestar al
        proveedor por cada recepcionista.

        Se permite hacérselo a uno mismo: no tiene sentido bloquearlo, quien
        está autenticado ya puede cambiarla desde Mi cuenta.
        """
        usuario = self.get_object()
        password = generar_password()
        usuario.set_password(password)
        usuario.save(update_fields=['password'])

        # Sus sesiones abiertas mueren: si se restablece la contraseña es
        # porque la anterior ya no debe servirle a nadie.
        for outstanding in OutstandingToken.objects.filter(user_id=usuario.id):
            BlacklistedToken.objects.get_or_create(token=outstanding)

        return Response({
            **UsuarioSerializer(usuario).data,
            'password': password,
        })
