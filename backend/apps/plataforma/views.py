"""API del panel del proveedor: ``/api/plataforma/...``.

Fase 1: entrar y ver. Todo aquí es de SOLO LECTURA sobre los gimnasios --
crear, configurar y suspender llegan después, y son operaciones con
consecuencias que merecen su propia revisión.

Estas rutas están en ``TENANT_EXEMPT_PATHS``: no pertenecen a ningún
gimnasio, así que ``TenantMiddleware`` no abre transacción de tenant y
``app.tenant_id`` queda sin fijar. Consecuencia buscada: si por descuido
alguna vista de aquí consultara una tabla de negocio, RLS devolvería CERO
filas en vez de mezclar datos de gimnasios distintos. Los recuentos del
listado no vienen de esas tablas, sino de ``v_plataforma_resumen_tenants``
(ver el docstring de la migración ``plataforma.0002``).
"""
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar_auditoria
from apps.core.middleware import invalidar_cache_tenant
from apps.core.tenant import tenant_context
from apps.organizacion.models import Usuario

from .aprovisionamiento import AprovisionamientoError, aprovisionar_tenant, generar_password
from .facturacion import (
    FacturacionError,
    anular_factura,
    emitir_factura,
    marcar_mora,
    marcar_pagada,
)
from .auth import (
    AutenticacionPlataforma,
    EsAdministradorDePlataforma,
    EsPersonalDePlataforma,
    crear_tokens,
    refrescar_acceso,
)
from .metricas import anexar_recuentos
from .models import FacturaSuscripcion, PlanSuscripcion, Suscripcion, Tenant, UsuarioPlataforma
from .serializers import (
    AsignarSuscripcionSerializer,
    CambiarPasswordPlataformaSerializer,
    CambioEstadoSerializer,
    FacturaSuscripcionSerializer,
    PlanSuscripcionSerializer,
    SuscripcionDetalleSerializer,
    LoginPlataformaSerializer,
    RefrescoPlataformaSerializer,
    RestablecerPasswordSerializer,
    UsuarioDeGimnasioSerializer,
    TenantConfiguracionSerializer,
    TenantCrearSerializer,
    TenantDetalleSerializer,
    TenantListaSerializer,
    UsuarioPlataformaSerializer,
)
from .subdominios import buscar_disponible


class LoginPlataformaView(GenericAPIView):
    """``POST /api/plataforma/login/``: correo + contraseña -> pareja de tokens."""

    authentication_classes = []
    permission_classes = []
    serializer_class = LoginPlataformaSerializer

    def post(self, request):
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        correo = entrada.validated_data['correo'].strip()
        # `correo` es CITEXT en el esquema y único de forma insensible a
        # mayúsculas: se busca igual para que "Ana@x.com" y "ana@x.com" sean
        # la misma cuenta.
        usuario = UsuarioPlataforma.objects.filter(correo__iexact=correo).first()

        # Mismo mensaje para "no existe", "contraseña mala" y "cuenta
        # desactivada": distinguirlos permite averiguar qué correos son
        # cuentas válidas del proveedor probando uno a uno.
        if usuario is None or not usuario.activo or not usuario.check_password(
            entrada.validated_data['password'],
        ):
            return Response(
                {'detail': 'Correo o contraseña incorrectos.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response({
            **crear_tokens(usuario),
            'usuario': UsuarioPlataformaSerializer(usuario).data,
        })


class RefrescoPlataformaView(GenericAPIView):
    """``POST /api/plataforma/refresh/``: nuevo access token."""

    authentication_classes = []
    permission_classes = []
    serializer_class = RefrescoPlataformaSerializer

    def post(self, request):
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        # Se captura y se responde 401 a mano en vez de dejar propagar
        # `AuthenticationFailed`: DRF degrada el 401 a 403 cuando la vista no
        # declara ninguna clase de autenticación (sin autenticadores no sabe
        # qué cabecera `WWW-Authenticate` emitir), y un refresh caducado es un
        # 401 de manual -- el frontend distingue "vuelve a entrar" de "no
        # tienes permiso" por ese código.
        try:
            return Response(refrescar_acceso(entrada.validated_data['refresh']))
        except AuthenticationFailed as error:
            return Response({'detail': error.detail}, status=status.HTTP_401_UNAUTHORIZED)


class YoPlataformaView(APIView):
    """``GET /api/plataforma/me/``: la cuenta del token, releída de la base."""

    authentication_classes = [AutenticacionPlataforma]
    permission_classes = [EsPersonalDePlataforma]

    def get(self, request):
        return Response(UsuarioPlataformaSerializer(request.user).data)


class PlanSuscripcionViewSet(viewsets.ModelViewSet):
    """``/api/plataforma/planes-suscripcion/``: el catálogo que vendes.

    Baja LÓGICA, nunca borrado: ``Suscripcion.plan_suscripcion`` es
    ``PROTECT``, y aunque no lo fuera, borrar un plan con contratos vivos
    dejaría el histórico de facturación sin poder explicar de dónde salió
    cada importe.
    """

    authentication_classes = [AutenticacionPlataforma]
    serializer_class = PlanSuscripcionSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [EsPersonalDePlataforma()]
        return [EsAdministradorDePlataforma()]

    def get_queryset(self):
        qs = PlanSuscripcion.objects.all().order_by('precio_por_sede', 'nombre')
        # Por defecto solo los vigentes. La pantalla de gestión pide
        # `?incluir_inactivos=1` para poder reactivar uno dado de baja: si no,
        # la baja sería un viaje sin retorno.
        if self.request.query_params.get('incluir_inactivos', '') not in ('1', 'true', 'True'):
            qs = qs.filter(activo=True)
        return qs

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        plan.activo = False
        plan.save(update_fields=['activo'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CobrosView(APIView):
    """``/api/plataforma/cobros/``: quién te debe dinero.

    Es, para ti, lo que el informe de cartera es para tus gimnasios. No
    admite rango de fechas por el mismo motivo: una deuda no pertenece a un
    mes, sigue viva hasta que se cobra.
    """

    authentication_classes = [AutenticacionPlataforma]
    permission_classes = [EsPersonalDePlataforma]

    def get(self, request):
        hoy = timezone.localdate()
        suscripciones = (
            Suscripcion.objects
            .exclude(estado=Suscripcion.EstadoSuscripcion.CANCELADA)
            .select_related('tenant', 'plan_suscripcion')
            .prefetch_related('facturas')
        )

        deudores = []
        total = Decimal('0')
        for suscripcion in suscripciones:
            pendientes = [
                f for f in suscripcion.facturas.all()
                if f.estado == FacturaSuscripcion.EstadoFactura.EMITIDA
            ]
            if not pendientes:
                continue

            saldo = sum((f.monto for f in pendientes), Decimal('0'))
            total += saldo
            deudores.append({
                'tenant': {
                    'uuid_publico': str(suscripcion.tenant.uuid_publico),
                    'nombre_comercial': suscripcion.tenant.nombre_comercial,
                    'subdominio': suscripcion.tenant.subdominio,
                    'estado': suscripcion.tenant.estado,
                },
                'plan': suscripcion.plan_suscripcion.nombre,
                'estado_suscripcion': suscripcion.estado,
                'saldo': str(saldo),
                'facturas': FacturaSuscripcionSerializer(
                    sorted(pendientes, key=lambda f: f.periodo_inicio), many=True,
                ).data,
                # Días que lleva vencida la factura pendiente más antigua,
                # ya descontado el plazo de gracia. Ordena la conversación
                # mejor que el importe: quien lleva tres meses sin pagar es
                # más urgente que quien debe más y va al día.
                #
                # Nunca negativo: una factura recién emitida y todavía dentro
                # de su plazo no está atrasada, está al día. Enseñar "-5 días
                # de atraso" no significa nada para quien lo lee.
                'dias_de_atraso': max(
                    0,
                    max(
                        (hoy - f.fecha_emision).days - suscripcion.dias_gracia
                        for f in pendientes
                    ),
                ),
            })

        deudores.sort(key=lambda d: d['dias_de_atraso'], reverse=True)
        return Response({
            'deudores': deudores,
            'totales': {'saldo': str(total), 'gimnasios': len(deudores)},
        })


class CambiarPasswordPlataformaView(APIView):
    """``POST /api/plataforma/cambiar-password/``.

    Al cambiar la contraseña, TODOS los tokens ya emitidos de esta cuenta
    dejan de valer: llevan una huella del hash anterior que deja de coincidir
    (ver ``auth.huella_password``). Por eso se devuelve una pareja nueva, para
    que la sesión desde la que se hizo el cambio no se caiga sola.
    """

    authentication_classes = [AutenticacionPlataforma]
    permission_classes = [EsPersonalDePlataforma]

    def post(self, request):
        entrada = CambiarPasswordPlataformaSerializer(
            data=request.data, context={'request': request},
        )
        entrada.is_valid(raise_exception=True)

        usuario = request.user
        usuario.set_password(entrada.validated_data['password_nueva'])
        usuario.save(update_fields=['password_hash'])

        return Response({
            'detail': 'Contraseña actualizada. Se cerraron las demás sesiones.',
            **crear_tokens(usuario),
        })


class TenantViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    """``/api/plataforma/tenants/``: los gimnasios contratantes.

    Se busca por ``uuid_publico`` y no por ``id``: la columna existe
    justamente para que las URLs no dejen enumerar la cartera de clientes
    contando 1, 2, 3.

    Leer lo puede hacer cualquier empleado del proveedor; CREAR, EDITAR y
    CAMBIAR DE ESTADO solo el rol ``administrador``. Soporte entra a
    diagnosticar, no a tocar la configuración de un cliente.

    No hay ``destroy``: un gimnasio no se borra. El ciclo de vida termina en
    ``cancelado``, que fija la fecha de purga para que un proceso posterior
    (RF-21) se ocupe de los datos con conocimiento de causa.
    """

    authentication_classes = [AutenticacionPlataforma]
    lookup_field = 'uuid_publico'

    _ACCIONES_DE_ESCRITURA = (
        'create', 'update', 'partial_update', 'estado', 'restablecer_password',
        'cancelar_suscripcion', 'emitir_factura_del_periodo',
        'pagar_factura', 'anular_factura_emitida',
    )

    def _es_escritura(self):
        # `suscripcion` sirve GET y POST en la misma acción: el permiso no
        # puede salir solo del nombre.
        if self.action == 'suscripcion':
            return self.request.method == 'POST'
        return self.action in self._ACCIONES_DE_ESCRITURA

    def get_permissions(self):
        if self._es_escritura():
            return [EsAdministradorDePlataforma()]
        return [EsPersonalDePlataforma()]

    #: Filtros del listado. ``estado`` acota por el ciclo de vida del contrato;
    #: ``buscar`` mira nombre, subdominio y correo del responsable.
    _ESTADOS = {estado for estado, _etiqueta in Tenant.EstadoTenant.choices}

    def get_serializer_class(self):
        if self.action == 'create':
            return TenantCrearSerializer
        if self.action in ('update', 'partial_update'):
            return TenantConfiguracionSerializer
        if self.action == 'estado':
            return CambioEstadoSerializer
        if self.action == 'restablecer_password':
            return RestablecerPasswordSerializer
        return TenantListaSerializer if self.action == 'list' else TenantDetalleSerializer

    def get_queryset(self):
        qs = Tenant.objects.all().order_by('nombre_comercial')

        if self.action != 'list':
            # La ficha enseña la suscripción vigente; se precarga para no
            # disparar una consulta por cada acceso al related manager.
            qs = qs.prefetch_related(
                Prefetch('suscripciones', queryset=Suscripcion.objects.select_related('plan_suscripcion')),
            )
            return qs

        estado = self.request.query_params.get('estado', '')
        if estado in self._ESTADOS:
            qs = qs.filter(estado=estado)

        buscar = self.request.query_params.get('buscar', '').strip()
        if buscar:
            from django.db.models import Q
            # Palabra a palabra y exigiéndolas todas, igual que el buscador de
            # clientes: "gim norte" encuentra "Gimnasio del Norte".
            for termino in buscar.split():
                qs = qs.filter(
                    Q(nombre_comercial__icontains=termino)
                    | Q(subdominio__icontains=termino)
                    | Q(correo__icontains=termino)
                    | Q(responsable__icontains=termino),
                )

        return qs

    # Los recuentos se calculan entrando en el contexto RLS de cada gimnasio
    # (ver `metricas.py`), así que se piden DESPUÉS de paginar: solo se paga
    # por las filas que se van a enseñar.
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        pagina = self.paginate_queryset(queryset)
        if pagina is not None:
            anexar_recuentos(pagina)
            return self.get_paginated_response(self.get_serializer(pagina, many=True).data)

        filas = list(queryset)
        anexar_recuentos(filas)
        return Response(self.get_serializer(filas, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        tenant = self.get_object()
        anexar_recuentos([tenant])
        return Response(self.get_serializer(tenant).data)

    # -- Escritura --------------------------------------------------------

    def create(self, request, *args, **kwargs):
        """Da de alta un gimnasio COMPLETO: sede, roles, permisos, semillas y
        usuario administrador (ver ``aprovisionamiento``).

        La contraseña la genera el servidor y se devuelve UNA sola vez, aquí.
        No se guarda en claro en ningún sitio ni se puede volver a consultar:
        si se pierde, se restablece, que es lo correcto.
        """
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        subdominio = datos.get('subdominio') or self._subdominio_libre(datos['subdominio_propuesto'])
        password = generar_password()

        try:
            tenant, sede, usuario = aprovisionar_tenant(
                nombre=datos['nombre_comercial'],
                subdominio=subdominio,
                correo_admin=datos['correo_admin'].strip().lower(),
                password_admin=password,
                nombre_sede=datos.get('nombre_sede') or 'Sede Principal',
                responsable=datos.get('responsable') or None,
                telefono=datos.get('telefono') or None,
                ciudad=datos.get('ciudad') or None,
                nit=datos.get('nit') or None,
                # Conexión de la APLICACIÓN, no la de superusuario: ver el
                # docstring de `aprovisionamiento`.
                conexion='default',
            )
        except AprovisionamientoError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            # Carrera: otro alta se quedó con el subdominio entre la
            # validación y el INSERT. La restricción única de la base es la
            # que decide, y aquí solo se traduce a un 400 legible.
            return Response(
                {'subdominio': [f'Ya existe un gimnasio con el subdominio "{subdominio}".']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # El subdominio nuevo pudo quedar cacheado como "no existe" si alguien
        # lo tecleó antes de crearlo. Sin esto, el gimnasio recién creado
        # rebotaría a sus usuarios durante el minuto siguiente.
        invalidar_cache_tenant(subdominio)

        anexar_recuentos([tenant])
        return Response(
            {
                **TenantDetalleSerializer(tenant).data,
                'acceso_inicial': {
                    'url': f'{subdominio}',
                    'correo': usuario.correo,
                    # Única vez que esta contraseña existe fuera del hash.
                    'password': password,
                    'sede': sede.nombre,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def _subdominio_libre(self, propuesta):
        return buscar_disponible(
            propuesta,
            lambda s: Tenant.objects.filter(subdominio__iexact=s).exists(),
        )

    def update(self, request, *args, **kwargs):
        """Edita la configuración. Siempre parcial: el panel manda solo lo que
        cambió y exigir la ficha entera invitaría a pisar campos sin querer."""
        tenant = self.get_object()
        entrada = self.get_serializer(tenant, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        entrada.save()

        tenant.refresh_from_db()
        anexar_recuentos([tenant])
        return Response(TenantDetalleSerializer(tenant).data)

    @action(detail=True, methods=['get'])
    def usuarios(self, request, uuid_publico=None):
        """``GET /api/plataforma/tenants/{uuid}/usuarios/``: quién trabaja en
        ese gimnasio.

        Existe para poder restablecer una contraseña sabiendo a quién, no
        para administrar personal ajeno: devuelve nombre, correo, rol y si
        está activo, y nada más.

        ``usuarios`` tiene RLS, así que hay que entrar en el contexto del
        gimnasio -- esta petición no tiene tenant fijado.
        """
        tenant = self.get_object()
        with tenant_context(tenant.id):
            filas = list(
                Usuario.objects.filter(tenant=tenant)
                .select_related('rol')
                .order_by('-activo', 'nombre'),
            )
            return Response(UsuarioDeGimnasioSerializer(filas, many=True).data)

    @action(detail=True, methods=['post'], url_path='restablecer-password')
    def restablecer_password(self, request, uuid_publico=None):
        """``POST /api/plataforma/tenants/{uuid}/restablecer-password/``.

        El rescate cuando un cliente no puede entrar. Genera una contraseña
        nueva y la devuelve UNA vez, igual que en el alta.

        Queda registrado en auditoría con ``usuario_plataforma_id``: es una
        operación que entrega el acceso a la cuenta de un cliente y no puede
        ser invisible. Se anota quién la hizo, sobre quién y cuándo -- nunca
        la contraseña.
        """
        tenant = self.get_object()
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        password = generar_password()

        with tenant_context(tenant.id):
            usuario = Usuario.objects.filter(
                pk=entrada.validated_data['usuario_id'], tenant=tenant,
            ).first()
            if usuario is None:
                # Puede ser un id de otro gimnasio: RLS ya lo hizo invisible,
                # así que aquí solo queda decir que no existe.
                return Response(
                    {'usuario_id': ['Ese usuario no existe en este gimnasio.']},
                    status=status.HTTP_404_NOT_FOUND,
                )

            usuario.set_password(password)
            usuario.save(update_fields=['password'])

            registrar_auditoria(
                tenant_id=tenant.id,
                usuario_id=usuario.id,
                usuario_plataforma_id=request.user.id,
                sede_id=None,
                entidad='usuarios',
                entidad_id=usuario.id,
                accion=Auditoria.AccionAuditoria.ACTUALIZAR,
                valor_anterior=None,
                # Nunca la contraseña: la traza dice QUÉ pasó, no cuál es.
                valor_nuevo={
                    'password_restablecida_por_soporte': True,
                    'usuario_plataforma': request.user.correo,
                },
            )

        # Las sesiones abiertas de ese usuario mueren: si se restablece la
        # contraseña es porque la anterior ya no debe servir a nadie.
        for outstanding in OutstandingToken.objects.filter(user_id=usuario.id):
            BlacklistedToken.objects.get_or_create(token=outstanding)

        return Response({
            'usuario': {'id': usuario.id, 'nombre': usuario.nombre, 'correo': usuario.correo},
            'password': password,
            'subdominio': tenant.subdominio,
        })

    # -- Suscripción y facturación ----------------------------------------

    def _suscripcion_vigente(self, tenant):
        return tenant.suscripciones.exclude(
            estado=Suscripcion.EstadoSuscripcion.CANCELADA,
        ).select_related('plan_suscripcion').prefetch_related('facturas').first()

    @action(detail=True, methods=['get', 'post'], url_path='suscripcion')
    def suscripcion(self, request, uuid_publico=None):
        """``GET`` devuelve la suscripción viva con sus facturas.
        ``POST`` contrata un plan, o cambia el que ya tenía.

        Cambiar de plan CIERRA la suscripción anterior y abre una nueva, en
        vez de reescribir la que había. La restricción ``uq_suscripciones_vigente``
        obliga a que solo haya una viva por gimnasio, y además así queda el
        histórico: qué plan tenía antes, desde cuándo y hasta cuándo. Sus
        facturas siguen colgando de la suscripción vieja, que es donde tienen
        sentido.
        """
        tenant = self.get_object()

        if request.method == 'GET':
            suscripcion = self._suscripcion_vigente(tenant)
            if suscripcion is None:
                return Response(None)
            return Response(SuscripcionDetalleSerializer(suscripcion).data)

        entrada = AsignarSuscripcionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        with transaction.atomic():
            anterior = self._suscripcion_vigente(tenant)
            if anterior is not None:
                anterior.estado = Suscripcion.EstadoSuscripcion.CANCELADA
                anterior.fecha_fin = timezone.localdate()
                anterior.save(update_fields=['estado', 'fecha_fin'])

            suscripcion = Suscripcion.objects.create(
                tenant=tenant,
                plan_suscripcion=datos['plan_suscripcion'],
                fecha_inicio=datos['fecha_inicio'],
                proximo_corte=datos['proximo_corte'],
                **({'dias_gracia': datos['dias_gracia']} if 'dias_gracia' in datos else {}),
            )

        return Response(
            SuscripcionDetalleSerializer(suscripcion).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='cancelar-suscripcion')
    def cancelar_suscripcion(self, request, uuid_publico=None):
        """Termina el contrato. NO toca el estado del gimnasio: dejar de
        cobrarle y apagarle el negocio son dos decisiones distintas, y la
        segunda tiene su propia acción con confirmación.

        Las facturas pendientes siguen pendientes: cancelar un contrato no
        perdona lo ya facturado.
        """
        tenant = self.get_object()
        suscripcion = self._suscripcion_vigente(tenant)
        if suscripcion is None:
            return Response(
                {'detail': 'Este gimnasio no tiene ninguna suscripción activa.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        suscripcion.estado = Suscripcion.EstadoSuscripcion.CANCELADA
        suscripcion.fecha_fin = timezone.localdate()
        suscripcion.save(update_fields=['estado', 'fecha_fin'])
        return Response(SuscripcionDetalleSerializer(suscripcion).data)

    @action(detail=True, methods=['post'], url_path='emitir-factura')
    def emitir_factura_del_periodo(self, request, uuid_publico=None):
        """Emite la factura del periodo que arranca en ``proximo_corte``."""
        tenant = self.get_object()
        suscripcion = self._suscripcion_vigente(tenant)
        if suscripcion is None:
            return Response(
                {'detail': 'Este gimnasio no tiene ninguna suscripción activa.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            factura = emitir_factura(suscripcion)
        except FacturacionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        marcar_mora(suscripcion)
        return Response(
            FacturaSuscripcionSerializer(factura).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='facturas/(?P<factura_id>[0-9]+)/pagar')
    def pagar_factura(self, request, uuid_publico=None, factura_id=None):
        return self._operar_sobre_factura(marcar_pagada, factura_id)

    @action(detail=True, methods=['post'], url_path='facturas/(?P<factura_id>[0-9]+)/anular')
    def anular_factura_emitida(self, request, uuid_publico=None, factura_id=None):
        return self._operar_sobre_factura(anular_factura, factura_id)

    def _operar_sobre_factura(self, operacion, factura_id):
        """El id de la factura se busca DENTRO del gimnasio de la URL: así un
        id de otro cliente devuelve 404 en vez de operarse por error."""
        tenant = self.get_object()
        factura = FacturaSuscripcion.objects.filter(
            pk=factura_id, suscripcion__tenant=tenant,
        ).select_related('suscripcion').first()
        if factura is None:
            return Response(
                {'detail': 'Esa factura no existe en este gimnasio.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            operacion(factura)
        except FacturacionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(FacturaSuscripcionSerializer(factura).data)

    @action(detail=True, methods=['post'])
    def estado(self, request, uuid_publico=None):
        """``POST /api/plataforma/tenants/{uuid}/estado/``: cambia el ciclo de
        vida del gimnasio.

        Acción aparte del PATCH a propósito. Pasar a ``suspendido`` o
        ``cancelado`` deja fuera a TODOS los usuarios de ese gimnasio en la
        siguiente petición —``TenantMiddleware`` excluye esos estados al
        resolver el subdominio—, y eso no puede ocurrir de refilón mientras
        se corrige un teléfono.
        """
        tenant = self.get_object()
        entrada = self.get_serializer(data=request.data, context={'tenant': tenant, 'request': request})
        entrada.is_valid(raise_exception=True)

        nuevo = entrada.validated_data['estado']
        campos = ['estado']
        tenant.estado = nuevo

        if nuevo == Tenant.EstadoTenant.CANCELADO:
            hoy = timezone.localdate()
            tenant.fecha_cancelacion = hoy
            # RF-21: retención 30+60 días. La restricción `ck_tenants_purga`
            # exige que la purga sea POSTERIOR a la cancelación.
            tenant.fecha_purga_datos = hoy + timedelta(days=91)
            campos += ['fecha_cancelacion', 'fecha_purga_datos']
        elif tenant.fecha_cancelacion is not None:
            # Vuelve a la vida: se limpian las fechas o el gimnasio quedaría
            # activo pero con una purga programada, y un proceso posterior
            # borraría los datos de un cliente que está operando.
            tenant.fecha_cancelacion = None
            tenant.fecha_purga_datos = None
            campos += ['fecha_cancelacion', 'fecha_purga_datos']

        tenant.save(update_fields=campos)

        # Imprescindible: el middleware cachea la resolución del subdominio
        # (60 s, incluidos los "no existe"). Sin invalidar, suspender tardaría
        # hasta un minuto en surtir efecto y reactivar otro tanto.
        invalidar_cache_tenant(tenant.subdominio)

        anexar_recuentos([tenant])
        return Response(TenantDetalleSerializer(tenant).data)
