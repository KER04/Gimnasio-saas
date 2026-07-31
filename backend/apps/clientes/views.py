"""Vistas de la API de clientes (Parte B del encargo, RF-03/RF-09/RF-16).

Igual que en ``apps.ventas.views`` (Parte D), cada vista declara su permiso
vía ``TienePermiso`` y no contiene lógica de negocio más allá de traducir
HTTP <-> Python: los errores de negocio (cédula repetida, sede ambigua...) se
devuelven como 400 (nunca 500) desde el propio serializer.
"""
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditoria.models import VistaMembresiaEstado, VistaVentaSaldo
from apps.core.permissions import TienePermiso
from apps.ventas.models import DetalleVenta, Pago

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

    def get_queryset(self):
        # Borrado lógico (Parte B3): un cliente eliminado desaparece de
        # listados/detalle/edición/borrado por defecto, pero su fila (y su
        # histórico de ventas, que referencia este id) sigue existiendo.
        qs = Cliente.objects.filter(eliminado_en__isnull=True).select_related('sede_origen')

        if self.action == 'list':
            buscar = self.request.query_params.get('buscar')
            if buscar:
                # Búsqueda por nombre O cédula en el mismo parámetro (Parte
                # B3), disponible también para el buscador del POS (Parte B1:
                # este es el único endpoint de clientes que existe ahora).
                qs = qs.filter(Q(nombre__icontains=buscar) | Q(cedula__icontains=buscar))
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
