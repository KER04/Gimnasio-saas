"""Gastos e ingresos varios (RF-24 y RF-07).

Movimientos de caja SIN venta asociada: no tienen cliente, ni líneas, ni
comprobante numerado. Por eso viven aparte de ``views.py``, que es todo POS.

## Por qué se auditan y las ventas se anulan

Una venta mal hecha se ANULA: queda la fila, marcada, y el histórico explica
lo que pasó. La tabla ``gastos`` no tiene columna ``estado``, así que ahí no
cabe esa figura -- corregir un error solo puede ser editar o borrar de
verdad.

Borrar sin dejar rastro un apunte de dinero es exactamente lo que no debe
poder hacerse en silencio, así que cada edición y cada borrado deja traza en
``auditoria`` con quién, cuándo y qué valores había antes. Es lo que
sustituye aquí a la anulación.
"""
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar_auditoria
from apps.core.permissions import TienePermiso

from .models import CategoriaGasto, CategoriaIngreso, Gasto, IngresoOtro
from .serializers_caja import (
    CategoriaGastoSerializer,
    CategoriaIngresoSerializer,
    GastoSerializer,
    IngresoOtroSerializer,
)


def _rango(request, qs):
    """Filtro por ``?desde=`` y ``?hasta=`` (inclusive), sobre la columna
    ``fecha``, que es un DATE: no hay zona horaria que resolver aquí."""
    desde = request.query_params.get('desde')
    hasta = request.query_params.get('hasta')
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    return qs


class _MovimientoDeCajaViewSet(viewsets.ModelViewSet):
    """Comportamiento común de gastos e ingresos varios.

    Lo único que cambia entre ambos es el modelo, el serializer y el nombre
    de la entidad en la auditoría.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'gastos.gestionar'

    #: Nombre de la tabla, tal como se anota en `auditoria.entidad`.
    entidad = None
    #: Campos cuyo valor anterior se guarda al editar o borrar.
    campos_auditados = ()

    def get_queryset(self):
        # RLS ya acota al tenant.
        qs = self.queryset_base().order_by('-fecha', '-id')
        sede = self.request.query_params.get('sede_id')
        if sede:
            qs = qs.filter(sede_id=sede)
        categoria = self.request.query_params.get('categoria')
        if categoria:
            qs = qs.filter(**{f'{self.campo_categoria}_id': categoria})
        return _rango(self.request, qs)

    def _foto(self, objeto):
        """Los valores que importan de una fila, para la traza."""
        return {
            campo: str(getattr(objeto, campo))
            for campo in self.campos_auditados
        }

    def _auditar(self, objeto, accion, valor_anterior=None, valor_nuevo=None):
        registrar_auditoria(
            tenant_id=objeto.tenant_id,
            usuario_id=self.request.user.id,
            sede_id=objeto.sede_id,
            entidad=self.entidad,
            entidad_id=objeto.id,
            accion=accion,
            valor_anterior=valor_anterior,
            valor_nuevo=valor_nuevo,
        )

    def perform_create(self, serializer):
        # tenant y usuario NUNCA salen del cuerpo: uno del middleware y otro
        # del token. Si vinieran de fuera se podría registrar un gasto en
        # otro gimnasio o a nombre de otra persona.
        objeto = serializer.save(
            tenant_id=self.request.tenant_id,
            usuario=self.request.user,
        )
        self._auditar(objeto, Auditoria.AccionAuditoria.CREAR, valor_nuevo=self._foto(objeto))

    def perform_update(self, serializer):
        anterior = self._foto(serializer.instance)
        objeto = serializer.save()
        self._auditar(
            objeto, Auditoria.AccionAuditoria.ACTUALIZAR,
            valor_anterior=anterior, valor_nuevo=self._foto(objeto),
        )

    def destroy(self, request, *args, **kwargs):
        """Borrado REAL, con traza.

        Nada referencia a un gasto ni a un ingreso suelto, así que la fila se
        puede eliminar sin romper nada. Lo que no puede es desaparecer en
        silencio: la traza guarda el importe, la fecha y la descripción que
        tenía, para que el descuadre de un cierre se pueda explicar.
        """
        objeto = self.get_object()
        foto = self._foto(objeto)
        with transaction.atomic():
            self._auditar(objeto, Auditoria.AccionAuditoria.ELIMINAR, valor_anterior=foto)
            objeto.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GastoViewSet(_MovimientoDeCajaViewSet):
    """``/api/gastos/`` (``gastos.gestionar``): arriendo, nómina, servicios.

    Filtros: ``?desde=``, ``?hasta=``, ``?sede_id=``, ``?categoria=``.
    """

    serializer_class = GastoSerializer
    entidad = 'gastos'
    campo_categoria = 'categoria_gasto'
    campos_auditados = ('monto', 'fecha', 'descripcion', 'categoria_gasto_id')

    def queryset_base(self):
        return Gasto.objects.select_related('categoria_gasto', 'sede', 'usuario')


class IngresoOtroViewSet(_MovimientoDeCajaViewSet):
    """``/api/ingresos/`` (``gastos.gestionar``): matrícula, casillero,
    alquiler de espacio. Dinero que entra sin venta detrás.

    Aparece en el corte de caja automáticamente: ``v_corte_diario`` suma
    estos ingresos junto con los pagos de ventas.
    """

    serializer_class = IngresoOtroSerializer
    entidad = 'ingresos_otros'
    campo_categoria = 'categoria_ingreso'
    campos_auditados = ('monto', 'fecha', 'descripcion', 'forma_pago', 'categoria_ingreso_id')

    def queryset_base(self):
        return IngresoOtro.objects.select_related('categoria_ingreso', 'sede', 'usuario')


class CategoriaGastoListView(ListAPIView):
    """``GET /api/categorias-gasto/``: para el desplegable del formulario.

    Solo lectura: las seis categorías se siembran al crear el gimnasio
    (RF-24) y cubren el catálogo del encargo. Editarlas sería otra pantalla.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'gastos.gestionar'
    serializer_class = CategoriaGastoSerializer

    def get_queryset(self):
        return CategoriaGasto.objects.filter(activa=True).order_by('nombre')


class CategoriaIngresoListView(ListAPIView):
    """``GET /api/categorias-ingreso/``: idem para los ingresos varios."""

    permission_classes = [TienePermiso]
    permiso_requerido = 'gastos.gestionar'
    serializer_class = CategoriaIngresoSerializer

    def get_queryset(self):
        return CategoriaIngreso.objects.filter(activa=True).order_by('nombre', 'subcategoria')
