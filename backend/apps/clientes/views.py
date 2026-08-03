"""Vistas de la API de clientes (Parte B del encargo, RF-03/RF-09/RF-16).

Igual que en ``apps.ventas.views`` (Parte D), cada vista declara su permiso
vía ``TienePermiso`` y no contiene lógica de negocio más allá de traducir
HTTP <-> Python: los errores de negocio (cédula repetida, sede ambigua...) se
devuelven como 400 (nunca 500) desde el propio serializer.
"""
from decimal import Decimal

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditoria.models import VistaMembresiaEstado, VistaVentaSaldo
from apps.core.permissions import TienePermiso
from apps.membresias.models import Plan
from apps.ventas.models import DetalleVenta, Pago, Venta
from apps.ventas.serializers import VentaSerializer

from .models import Cliente
from .serializers import (
    ClienteResumenSerializer,
    ClienteSerializer,
    MembresiaEstadoSerializer,
    VentaSaldoSerializer,
)


class ClienteViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """``/api/clientes/``: listar+buscar, crear, ver detalle, editar, borrado
    lógico, y las dos consultas de ficha (membresías, deuda).

    ``permiso_requerido`` cubre 'list'/'retrieve' (y las dos acciones de
    ficha) con ``clientes.ver``; ``permisos_por_accion`` sube la exigencia a
    ``clientes.gestionar`` para crear/editar/borrar (Parte B2 de la tabla del
    encargo).
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'clientes.ver'
    permisos_por_accion = {
        'create': 'clientes.gestionar',
        'update': 'clientes.gestionar',
        'partial_update': 'clientes.gestionar',
        'destroy': 'clientes.gestionar',
    }
    serializer_class = ClienteSerializer

    #: filtro ``?estado=`` (además de ``sin_membresia``, aparte). No incluye
    #: ``cancelada``: no es un estado que el listado permita filtrar (la
    #: membresía vigente de un cliente nunca es una cancelada, ver
    #: ``get_queryset``).
    _ESTADOS_FILTRABLES = {
        VistaMembresiaEstado.EstadoCalculado.ACTIVA,
        VistaMembresiaEstado.EstadoCalculado.POR_VENCER,
        VistaMembresiaEstado.EstadoCalculado.VENCE_HOY,
        VistaMembresiaEstado.EstadoCalculado.VENCIDA,
    }

    def get_queryset(self):
        # Borrado lógico (Parte B3): un cliente eliminado desaparece de
        # listados/detalle/edición/borrado por defecto, pero su fila (y su
        # histórico de ventas, que referencia este id) sigue existiendo.
        qs = Cliente.objects.filter(eliminado_en__isnull=True).select_related('sede_origen')

        if self.action == 'list':
            # Import perezoso: evita el ciclo de import entre `apps.clientes`
            # y `apps.asistencia` (mismo motivo que en la action `asistencias`
            # más abajo -- esa app no depende de `apps.clientes` en sus vistas).
            from apps.asistencia.models import Asistencia

            # Membresía "vigente" del listado (RF-16): si el cliente tiene
            # varias membresías ACTIVAS a la vez (decisión 23), se muestra la
            # de fecha_fin más lejana. Se excluyen las canceladas: una
            # membresía cancelada nunca es "la vigente" aunque su fecha_fin
            # sea la más lejana. El estado sale YA CALCULADO de
            # `v_membresias_estado` (zona horaria del gimnasio) -- no se
            # recalcula aquí ni se usa CURRENT_DATE.
            membresia_vigente_qs = (
                VistaMembresiaEstado.objects.filter(cliente_id=OuterRef('pk'))
                .exclude(estado_calculado=VistaMembresiaEstado.EstadoCalculado.CANCELADA)
                .order_by('-fecha_fin')
            )
            membresia_vigente_qs = membresia_vigente_qs.annotate(
                plan_nombre=Subquery(
                    Plan.objects.filter(pk=OuterRef('plan_id')).values('nombre')[:1]
                ),
            )

            ultima_visita_qs = (
                Asistencia.objects.filter(cliente_id=OuterRef('pk'))
                .order_by('-fecha_hora')
                .values('fecha_hora')[:1]
            )

            # Subquery/annotate (no un query por cliente): estas cinco
            # columnas se resuelven como subconsultas escalares DENTRO de la
            # misma sentencia SELECT del listado, así que el número de
            # consultas no crece con el número de clientes de la página (ver
            # `ClienteListadoRendimientoTestCase.test_mismo_numero_de_consultas...`).
            qs = qs.annotate(
                membresia_plan_id=Subquery(membresia_vigente_qs.values('plan_id')[:1]),
                membresia_plan_nombre=Subquery(membresia_vigente_qs.values('plan_nombre')[:1]),
                membresia_fecha_fin=Subquery(membresia_vigente_qs.values('fecha_fin')[:1]),
                membresia_dias_restantes=Subquery(membresia_vigente_qs.values('dias_restantes')[:1]),
                membresia_estado_calculado=Subquery(membresia_vigente_qs.values('estado_calculado')[:1]),
                ultima_visita=Subquery(ultima_visita_qs),
            )

            buscar = self.request.query_params.get('buscar')
            if buscar:
                # Búsqueda por nombre O cédula en el mismo parámetro (Parte
                # B3), disponible también para el buscador del POS (Parte B1:
                # este es el único endpoint de clientes que existe ahora).
                qs = qs.filter(Q(nombre__icontains=buscar) | Q(cedula__icontains=buscar))

            estado = self.request.query_params.get('estado')
            if estado == 'sin_membresia':
                qs = qs.filter(membresia_fecha_fin__isnull=True)
            elif estado in self._ESTADOS_FILTRABLES:
                qs = qs.filter(membresia_estado_calculado=estado)

            plan_id = self.request.query_params.get('plan')
            if plan_id:
                qs = qs.filter(membresia_plan_id=plan_id)

            qs = qs.order_by('nombre')

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ClienteResumenSerializer
        return ClienteSerializer

    def destroy(self, request, *args, **kwargs):
        """Borrado SIEMPRE lógico (Parte B3): marca ``eliminado_en``, nunca
        ejecuta un DELETE real -- el histórico de ventas del cliente
        (``Venta.cliente``, ``on_delete=PROTECT``) debe sobrevivir intacto."""
        cliente = self.get_object()
        cliente.eliminado_en = timezone.now()
        cliente.save(update_fields=['eliminado_en'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def membresias(self, request, pk=None):
        """``GET /api/clientes/{id}/membresias/`` (``clientes.ver``): estado
        CALCULADO (RF-16), no el almacenado -- se lee directo de
        ``v_membresias_estado`` (``VistaMembresiaEstado``), sin reimplementar
        la lógica de vencimiento en Python. Un cliente puede tener varias
        membresías activas a la vez (decisión 23): se devuelven TODAS, no
        "la" membresía.
        """
        cliente = self.get_object()
        membresias = (
            VistaMembresiaEstado.objects.filter(cliente_id=cliente.id)
            .order_by('-fecha_fin')
        )
        datos = MembresiaEstadoSerializer(membresias, many=True).data
        return Response(datos)

    @action(detail=True, methods=['get'])
    def deuda(self, request, pk=None):
        """``GET /api/clientes/{id}/deuda/`` (``clientes.ver``): cartera del
        cliente (RF-09). Usa ``v_ventas_saldo`` para el saldo por venta; NO
        exige ``costos.ver`` (no se filtran márgenes, sencillamente no se
        incluyen campos de costo en la respuesta -- ``DetalleConceptoSerializer``
        no los expone en absoluto).
        """
        cliente = self.get_object()
        ventas_con_saldo = (
            VistaVentaSaldo.objects.filter(cliente_id=cliente.id, saldo__gt=0)
            .order_by('fecha_hora')
        )

        resultado = []
        total_adeudado = Decimal('0')
        for venta_saldo in ventas_con_saldo:
            resultado.append({
                'venta_id': venta_saldo.venta_id,
                'fecha_hora': venta_saldo.fecha_hora,
                'total': venta_saldo.total,
                'total_pagado': venta_saldo.total_pagado,
                'saldo': venta_saldo.saldo,
                'detalles': DetalleVenta.objects.filter(venta_id=venta_saldo.venta_id),
                'abonos': (
                    Pago.objects.filter(venta_id=venta_saldo.venta_id, anulado=False)
                    .order_by('fecha_hora')
                ),
            })
            total_adeudado += venta_saldo.saldo

        return Response({
            'total_adeudado': str(total_adeudado),
            'ventas': VentaSaldoSerializer(resultado, many=True).data,
        })

    @action(detail=True, methods=['get'])
    def compras(self, request, pk=None):
        """``GET /api/clientes/{id}/compras/`` (``clientes.ver``): historial
        de ventas del cliente, más reciente primero y paginado (Parte B de
        la ficha, pestaña "compras").

        Reutiliza ``VentaSerializer`` de ``apps.ventas`` -- las mismas
        líneas, los mismos pagos y el mismo criterio para ocultar
        ``costo_unitario`` a quien no tenga ``costos.ver`` (Parte D del
        encargo de ventas/POS) -- para no reimplementar esa lógica aquí.
        Incluye también las ventas anuladas, marcadas como tales
        (``estado='anulada'``): el histórico de compras no se oculta.
        """
        cliente = self.get_object()
        ventas = (
            Venta.objects.filter(cliente=cliente)
            .select_related('sede', 'cliente', 'usuario', 'anulada_por')
            .prefetch_related('detalles', 'pagos')
            .order_by('-fecha_hora')
        )

        page = self.paginate_queryset(ventas)
        objetos = page if page is not None else ventas
        serializer = VentaSerializer(objetos, many=True, context=self.get_serializer_context())

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def asistencias(self, request, pk=None):
        """``GET /api/clientes/{id}/asistencias/`` (``clientes.ver``):
        historial de ingresos del cliente, más reciente primero y paginado
        -- completa la pestaña de asistencia de la ficha (RF-03, RF-15).

        Importa de ``apps.asistencia`` en vez de al revés (esa app no
        depende de ``apps.clientes`` en sus vistas) para no crear un import
        circular entre los dos módulos.
        """
        from apps.asistencia.models import Asistencia
        from apps.asistencia.serializers import AsistenciaSerializer

        cliente = self.get_object()
        asistencias = (
            Asistencia.objects.filter(cliente=cliente)
            .select_related('sede', 'autorizado_por', 'venta')
            .order_by('-fecha_hora')
        )

        page = self.paginate_queryset(asistencias)
        objetos = page if page is not None else asistencias
        serializer = AsistenciaSerializer(objetos, many=True, context=self.get_serializer_context())

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
