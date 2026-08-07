"""Vistas de la API de inventario: productos, categorías y kardex.

Las vistas no contienen lógica de negocio: la escritura de movimientos
delega en ``apps.inventario.services.registrar_movimiento``, y estas solo
traducen HTTP <-> Python y devuelven los errores de negocio como 400 (nunca
500).

Permisos: leer exige ``inventario.ver``; crear, editar y dar de baja exigen
``inventario.gestionar``.
"""
from django.db import IntegrityError, transaction
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.core.permissions import TienePermiso
from apps.core.sedes import acotar_por_sede
from apps.organizacion.models import Sede

from .models import CategoriaProducto, MovimientoInventario, Producto
from .serializers import (
    CategoriaProductoSerializer,
    MovimientoInputSerializer,
    MovimientoInventarioSerializer,
    ProductoAdminSerializer,
    ProductoSerializer,
)
from .services import InventarioError, registrar_movimiento

#: Acciones de escritura, que suben la exigencia a ``inventario.gestionar``.
_PERMISOS_ESCRITURA = {
    'create': 'inventario.gestionar',
    'update': 'inventario.gestionar',
    'partial_update': 'inventario.gestionar',
    'destroy': 'inventario.gestionar',
}


def _quiere_inactivos(request):
    return request.query_params.get('incluir_inactivos', '').lower() in ('1', 'true')


def _solo_activos(vista):
    """Si esta petición debe ver ÚNICAMENTE lo activo.

    El filtro es del LISTADO y de nadie más. Aplicado a las acciones de
    detalle convertía la baja lógica en irreversible: para reactivar hay que
    hacer ``PATCH {activo: true}`` sobre una fila que, por definición, está
    inactiva -- y si el queryset la escondía, ese PATCH respondía 404. La
    casilla "Activo" del formulario no podía volver a marcarse nunca.

    El POS sigue viendo solo lo activo: lista sin ``?incluir_inactivos``.
    """
    return vista.action == 'list' and not _quiere_inactivos(vista.request)


class CategoriaProductoViewSet(viewsets.ModelViewSet):
    """``/api/categorias-producto/``.

    El borrado es LÓGICO (``activa=False``): ``Producto.categoria_producto``
    es ``on_delete=PROTECT``, así que borrar de verdad una categoría con
    productos reventaría, y además dejaría sin clasificar el histórico.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'inventario.ver'
    permisos_por_accion = _PERMISOS_ESCRITURA
    serializer_class = CategoriaProductoSerializer

    def get_queryset(self):
        qs = CategoriaProducto.objects.order_by('nombre')
        if _solo_activos(self):
            qs = qs.filter(activa=True)
        return qs

    def perform_create(self, serializer):
        # El tenant nunca se acepta del payload: lo impone el servidor a
        # partir del middleware multi-tenant.
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        categoria = self.get_object()
        categoria.activa = False
        categoria.save(update_fields=['activa'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductoViewSet(viewsets.ModelViewSet):
    """``/api/productos/``: catálogo de productos.

    Antes lo servía ``apps.ventas.views.ProductoListView`` (solo lectura); al
    pasar a CRUD se trasladó aquí, junto al modelo, conservando la misma URL,
    el mismo parámetro ``sede_id`` y el mismo permiso de lectura, de modo que
    el buscador del POS no nota el cambio.

    El borrado es LÓGICO (``activo=False``): ``DetalleVenta.producto`` es
    ``on_delete=PROTECT``, así que un producto ya vendido no se puede
    eliminar sin destruir el histórico de ventas.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'inventario.ver'
    permisos_por_accion = _PERMISOS_ESCRITURA

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return ProductoAdminSerializer
        return ProductoSerializer

    def get_queryset(self):
        qs = Producto.objects.select_related('categoria_producto').order_by('nombre')

        # Por defecto solo activos, que es lo que espera el POS. La pantalla
        # de inventario pide también los dados de baja para poder
        # reactivarlos, y lo hace explícito con ?incluir_inactivos=1.
        if _solo_activos(self):
            qs = qs.filter(activo=True)

        buscar = self.request.query_params.get('buscar')
        if buscar:
            # Palabra a palabra y todas obligatorias, igual que el buscador
            # de clientes: "whey choco" encuentra "Proteína Whey Chocolate".
            from django.db.models import Q
            for termino in buscar.split():
                qs = qs.filter(Q(nombre__icontains=termino) | Q(codigo_barras__icontains=termino))

        categoria = self.request.query_params.get('categoria')
        if categoria:
            qs = qs.filter(categoria_producto_id=categoria)

        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['sede_id'] = self.request.query_params.get('sede_id')
        return context

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        producto = self.get_object()
        producto.activo = False
        producto.save(update_fields=['activo'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _traducir_duplicado(self, guardar):
        """``uq_productos_codigo_barras`` (código único por tenant): un
        ``IntegrityError`` crudo sería un 500. Se envuelve en un SAVEPOINT
        (``atomic`` ANIDADO -- imprescindible porque ``ATOMIC_REQUESTS`` ya
        tiene la petición dentro de una transacción: sin él, capturar la
        excepción aquí dejaría envenenada la transacción exterior) para
        devolver un 400 con mensaje claro."""
        try:
            with transaction.atomic():
                return guardar()
        except IntegrityError as exc:
            if 'codigo_barras' in str(exc):
                return Response(
                    {'codigo_barras': 'Ya existe un producto con este código de barras.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise

    def create(self, request, *args, **kwargs):
        return self._traducir_duplicado(lambda: super(ProductoViewSet, self).create(request, *args, **kwargs))

    def update(self, request, *args, **kwargs):
        return self._traducir_duplicado(lambda: super(ProductoViewSet, self).update(request, *args, **kwargs))


class MovimientoInventarioViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet,
):
    """``/api/movimientos-inventario/``: kardex.

    Solo listar y crear: el kardex es un libro INMUTABLE. No hay editar ni
    borrar porque los errores se corrigen con un movimiento inverso, no
    reescribiendo el pasado.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'inventario.ver'
    permisos_por_accion = {'create': 'inventario.gestionar'}
    serializer_class = MovimientoInventarioSerializer

    def get_queryset(self):
        qs = (
            MovimientoInventario.objects
            .select_related('producto', 'sede', 'usuario')
            .order_by('-fecha_hora')
        )
        # Acotado a las sedes del usuario, y valida el `?sede=` que venga:
        # el libro de movimientos dice qué entró y salió de cada local, y eso
        # es información de ese local. Ver `apps.core.sedes`.
        qs = acotar_por_sede(self.request, qs)
        params = self.request.query_params

        producto = params.get('producto')
        if producto:
            qs = qs.filter(producto_id=producto)

        tipo = params.get('tipo')
        if tipo:
            qs = qs.filter(tipo=tipo)

        desde = params.get('desde')
        if desde:
            qs = qs.filter(fecha_hora__date__gte=desde)

        hasta = params.get('hasta')
        if hasta:
            qs = qs.filter(fecha_hora__date__lte=hasta)

        return qs

    def create(self, request, *args, **kwargs):
        entrada = MovimientoInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        producto = Producto.objects.filter(pk=datos['producto_id']).first()
        if producto is None:
            return Response({'producto_id': 'Producto no encontrado.'}, status=status.HTTP_400_BAD_REQUEST)

        sede = Sede.objects.filter(pk=datos['sede_id']).first()
        if sede is None:
            return Response({'sede_id': 'Sede no encontrada.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            movimiento = registrar_movimiento(
                tenant=request.tenant,
                producto=producto,
                sede=sede,
                usuario=request.user,
                tipo=datos['tipo'],
                cantidad=datos['cantidad'],
                costo_unitario=datos.get('costo_unitario'),
                motivo=datos.get('motivo'),
            )
        except InventarioError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        salida = MovimientoInventarioSerializer(movimiento, context=self.get_serializer_context())
        return Response(salida.data, status=status.HTTP_201_CREATED)
