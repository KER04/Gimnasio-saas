"""Vistas de la API de ventas/POS (Parte D del encargo).

Cada vista declara su permiso (Parte A, ``TienePermiso``) y NO contiene
lógica de negocio: la escritura (crear venta, anular, abonar) delega por
completo en ``apps.ventas.services``; estas vistas solo traducen HTTP <->
Python y devuelven errores de negocio como 400 (nunca 500).
"""
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.clientes.models import Cliente
from apps.core.permissions import TienePermiso
from apps.inventario.models import Producto
from apps.membresias.models import Plan

from .models import Venta
from .serializers import (
    AbonoInputSerializer,
    AnularVentaInputSerializer,
    ClienteResumenSerializer,
    PlanSerializer,
    ProductoSerializer,
    VentaCreateSerializer,
    VentaSerializer,
)
from .services import VentaError, anular_venta, registrar_abono


# ---------------------------------------------------------------------------
# Endpoints de apoyo del POS
# ---------------------------------------------------------------------------

class ProductoListView(ListAPIView):
    """``GET /api/productos/?buscar=<texto>&sede_id=<id>`` (``inventario.ver``)."""

    serializer_class = ProductoSerializer
    permission_classes = [TienePermiso]
    permiso_requerido = 'inventario.ver'

    def get_queryset(self):
        qs = Producto.objects.filter(activo=True).select_related('categoria_producto')
        buscar = self.request.query_params.get('buscar')
        if buscar:
            qs = qs.filter(Q(nombre__icontains=buscar) | Q(codigo_barras__icontains=buscar))
        return qs.order_by('nombre')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['sede_id'] = self.request.query_params.get('sede_id')
        return context


class PlanListView(ListAPIView):
    """``GET /api/planes/`` (``membresias.gestionar``)."""

    serializer_class = PlanSerializer
    permission_classes = [TienePermiso]
    permiso_requerido = 'membresias.gestionar'

    def get_queryset(self):
        return Plan.objects.filter(activo=True).order_by('nombre')


class ClienteListView(ListAPIView):
    """``GET /api/clientes/?buscar=<texto>`` (``clientes.ver``): busca por
    nombre o cédula, para el buscador del POS."""

    serializer_class = ClienteResumenSerializer
    permission_classes = [TienePermiso]
    permiso_requerido = 'clientes.ver'

    def get_queryset(self):
        qs = Cliente.objects.filter(eliminado_en__isnull=True)
        buscar = self.request.query_params.get('buscar')
        if buscar:
            qs = qs.filter(Q(nombre__icontains=buscar) | Q(cedula__icontains=buscar))
        return qs.order_by('nombre')


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
