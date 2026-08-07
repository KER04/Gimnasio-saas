"""Vistas de la API de asistencia (RF-15, sin biometría).

Cada vista declara su permiso (``TienePermiso``) y no contiene lógica de
negocio: la escritura delega por completo en
``apps.asistencia.services.registrar_asistencia``; estas vistas solo
traducen HTTP <-> Python y devuelven los errores de negocio de
``AsistenciaError``/subclases como 400/409/403 (nunca 500).
"""
import math
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditoria.models import VistaMembresiaEstado, VistaVentaSaldo
from apps.clientes.models import Cliente
from apps.clientes.serializers import ClienteResumenSerializer, MembresiaEstadoSerializer
from apps.core.permissions import TienePermiso
from apps.core.sedes import acotar_por_sede

from .models import Asistencia
from .serializers import AsistenciaInputSerializer, AsistenciaSerializer
from .services import AntipassbackError, AsistenciaError, AutorizacionError, registrar_asistencia

# Mismos estados de v_membresias_estado que cuentan como "vigente" en
# apps.asistencia.services._ESTADOS_VIGENTES -- duplicado deliberadamente
# pequeño (una tupla de constantes) para no crear un import cruzado
# services<->views solo por esto.
_ESTADOS_VIGENTES = (
    VistaMembresiaEstado.EstadoCalculado.ACTIVA,
    VistaMembresiaEstado.EstadoCalculado.VENCE_HOY,
    VistaMembresiaEstado.EstadoCalculado.POR_VENCER,
)


class AsistenciaViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """``/api/asistencias/``: registrar ingreso, listar, y el panel de
    check-in del recepcionista (``verificar``).

    ``permiso_requerido`` cubre 'create' con ``ventas.registrar`` (tabla del
    encargo: "registrar ingreso"); ``permisos_por_accion`` baja la exigencia
    a ``reportes.ver`` para 'list' y a ``clientes.ver`` para 'verificar'.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'ventas.registrar'
    permisos_por_accion = {'list': 'reportes.ver', 'verificar': 'clientes.ver'}
    serializer_class = AsistenciaSerializer

    def get_queryset(self):
        qs = (
            Asistencia.objects.select_related('cliente', 'sede', 'autorizado_por', 'venta')
            .order_by('-fecha_hora')
        )
        # Acotado a las sedes del usuario. Sustituye al filtro ``?sede=``
        # que había aquí: aquel dejaba pasar cualquier sede del gimnasio,
        # este solo las del usuario y rechaza el resto. Ver ``apps.core.sedes``.
        qs = acotar_por_sede(self.request, qs)
        params = self.request.query_params

        cliente_id = params.get('cliente')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)

        desde = params.get('desde')
        if desde:
            qs = qs.filter(fecha_hora__date__gte=desde)

        hasta = params.get('hasta')
        if hasta:
            qs = qs.filter(fecha_hora__date__lte=hasta)

        return qs

    def create(self, request, *args, **kwargs):
        entrada = AsistenciaInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        try:
            asistencia = registrar_asistencia(
                tenant=request.tenant,
                usuario=request.user,
                metodo=datos['metodo'],
                cedula=datos.get('cedula'),
                venta_id=datos.get('venta_id'),
                autorizado_por_id=datos.get('autorizado_por_id'),
                motivo_autorizacion=datos.get('motivo_autorizacion'),
            )
        except AutorizacionError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except AntipassbackError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        except AsistenciaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        salida = AsistenciaSerializer(asistencia, context=self.get_serializer_context())
        return Response(salida.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def verificar(self, request):
        """``GET /api/asistencias/verificar/?cedula=<n>`` (``clientes.ver``):
        el panel del recepcionista. NO registra nada, solo informa -- es lo
        que se mira antes de dejar pasar (RF-15)."""
        cedula = request.query_params.get('cedula')
        if not cedula:
            raise serializers.ValidationError({'cedula': 'Debes indicar la cédula a verificar.'})

        cliente = Cliente.objects.filter(cedula=cedula, eliminado_en__isnull=True).first()
        if cliente is None:
            return Response(
                {'detail': f'No existe un cliente con la cédula "{cedula}" en este gimnasio.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # TODAS las membresías del cliente (no solo las vigentes): el panel
        # también debe poder mostrar alertas de "vencida"/"por vencer"
        # (mismo criterio que apps.clientes.views.ClienteViewSet.membresias).
        membresias = list(
            VistaMembresiaEstado.objects.filter(cliente_id=cliente.id).order_by('-fecha_fin')
        )
        puede_ingresar = any(m.estado_calculado in _ESTADOS_VIGENTES for m in membresias)

        saldo_pendiente = (
            VistaVentaSaldo.objects.filter(cliente_id=cliente.id, saldo__gt=0)
            .aggregate(total=Sum('saldo'))['total']
        ) or Decimal('0')

        # Antipassback: misma ventana y misma consulta que
        # apps.asistencia.services.registrar_asistencia, para que lo que ve
        # el recepcionista en el panel coincida exactamente con lo que
        # pasaría si intentara registrar el ingreso ahora mismo.
        ultima = (
            Asistencia.objects.filter(cliente_id=cliente.id).order_by('-fecha_hora').first()
        )
        bloqueado_por_antipassback = False
        minutos_restantes_antipassback = None
        if ultima is not None:
            minutos_antipassback = request.tenant.minutos_antipassback
            transcurridos = (timezone.now() - ultima.fecha_hora).total_seconds() / 60
            if transcurridos < minutos_antipassback:
                bloqueado_por_antipassback = True
                minutos_restantes_antipassback = max(1, math.ceil(minutos_antipassback - transcurridos))

        return Response({
            'cliente': ClienteResumenSerializer(cliente).data,
            'membresias': MembresiaEstadoSerializer(membresias, many=True).data,
            'saldo_pendiente': str(saldo_pendiente),
            'puede_ingresar': puede_ingresar,
            'requiere_autorizacion': not puede_ingresar,
            'bloqueado_por_antipassback': bloqueado_por_antipassback,
            'minutos_restantes_antipassback': minutos_restantes_antipassback,
        })
