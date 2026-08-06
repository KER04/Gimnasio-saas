"""Vistas de la API de ventas/POS (Parte D del encargo).

Cada vista declara su permiso (Parte A, ``TienePermiso``) y NO contiene
lógica de negocio: la escritura (crear venta, anular, abonar) delega por
completo en ``apps.ventas.services``; estas vistas solo traducen HTTP <->
Python y devuelven errores de negocio como 400 (nunca 500).
"""
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.permissions import TienePermiso

from .models import Venta
from .serializers import (
    AbonoInputSerializer,
    AnularVentaInputSerializer,
    VentaCreateSerializer,
    VentaSerializer,
)
from .services import VentaError, anular_venta, registrar_abono


# ---------------------------------------------------------------------------
# Endpoints de apoyo del POS
#
# NOTA (Parte B1 del encargo de clientes, RF-03): el endpoint de búsqueda de
# clientes (antes ``ClienteListView``/``GET /api/clientes/?buscar=``) se
# trasladó por completo a ``apps.clientes`` -- ver
# ``apps/clientes/views.py::ClienteViewSet`` y ``apps/clientes/urls.py``. El
# buscador del POS sigue funcionando exactamente igual (mismo método HTTP,
# misma URL, mismo parámetro ``buscar``, mismo permiso ``clientes.ver``):
# solo cambió DÓNDE vive la implementación, para no tener dos endpoints de
# clientes duplicados.
# ---------------------------------------------------------------------------

# ``/api/productos/`` TAMPOCO se sirve ya desde aquí: se trasladó a
# ``apps.inventario`` al convertirse de listado de solo lectura en CRUD
# completo, junto al modelo ``Producto``. Sigue en la misma URL, con el mismo
# parámetro ``sede_id`` y el mismo permiso de lectura (``inventario.ver``):
# el buscador del POS no nota el cambio.


# ---------------------------------------------------------------------------
# Ventas
# ---------------------------------------------------------------------------

class VentaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """``/api/ventas/``: registrar, listar, ver detalle, anular y abonar.

    ``permiso_requerido`` cubre 'list', 'retrieve', 'create' y la acción
    'abonos' (los cuatro exigen ``ventas.registrar`` según la tabla del
    encargo); ``permisos_por_accion`` sube la exigencia a ``ventas.anular``
    solo para la acción 'anular'.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'ventas.registrar'
    permisos_por_accion = {'anular': 'ventas.anular'}
    serializer_class = VentaSerializer

    def get_queryset(self):
        qs = (
            Venta.objects.select_related('sede', 'cliente', 'usuario', 'anulada_por')
            .prefetch_related('detalles', 'pagos')
            .order_by('-fecha_hora')
        )
        params = self.request.query_params

        estado = params.get('estado')
        if estado:
            qs = qs.filter(estado=estado)

        desde = params.get('desde')
        if desde:
            qs = qs.filter(fecha_hora__date__gte=desde)

        hasta = params.get('hasta')
        if hasta:
            qs = qs.filter(fecha_hora__date__lte=hasta)

        return qs

    def create(self, request, *args, **kwargs):
        serializer = VentaCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        venta = serializer.save()
        salida = VentaSerializer(venta, context=self.get_serializer_context())
        return Response(salida.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def anular(self, request, pk=None):
        venta = self.get_object()
        entrada = AnularVentaInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        try:
            anular_venta(venta=venta, usuario=request.user, motivo=entrada.validated_data['motivo'])
        except VentaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        venta.refresh_from_db()
        salida = VentaSerializer(venta, context=self.get_serializer_context())
        return Response(salida.data)

    @action(detail=True, methods=['post'])
    def abonos(self, request, pk=None):
        venta = self.get_object()
        entrada = AbonoInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        try:
            registrar_abono(
                venta=venta,
                usuario=request.user,
                monto=entrada.validated_data['monto'],
                forma_pago=entrada.validated_data['forma_pago'],
            )
        except VentaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        venta.refresh_from_db()
        salida = VentaSerializer(venta, context=self.get_serializer_context())
        return Response(salida.data)
