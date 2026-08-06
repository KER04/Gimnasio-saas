"""Vistas de la API de membresías (Parte A del encargo de membresías).

Cada vista declara su permiso (``TienePermiso``) y no contiene lógica de
negocio: la escritura (asignar, renovar, cancelar) delega por completo en
``apps.membresias.services``; estas vistas solo traducen HTTP <-> Python y
devuelven errores de negocio como 400 (nunca 500).
"""
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditoria.models import VistaMembresiaEstado
from apps.clientes.models import Cliente
from apps.core.permissions import TienePermiso
from apps.organizacion.models import Sede

from .models import Membresia, Plan
from .serializers import (
    AsignarMembresiaInputSerializer,
    CancelarMembresiaInputSerializer,
    MembresiaPorVencerSerializer,
    MembresiaSerializer,
    PlanAdminSerializer,
    RenovarMembresiaInputSerializer,
)
from .services import MembresiaError, asignar_membresia, cancelar_membresia, renovar_membresia


class MembresiaViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet,
):
    """``/api/membresias/``: listar, ver detalle, asignar directamente,
    renovar y cancelar; más el tablero de vencimientos.

    ``permiso_requerido`` cubre 'list', 'retrieve', 'create', 'renovar' y
    'cancelar' con ``membresias.gestionar``; ``permisos_por_accion`` baja la
    exigencia a ``reportes.ver`` solo para 'por_vencer' (tablero de alertas
    de recepción, no gestión de membresías).
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'membresias.gestionar'
    permisos_por_accion = {'por_vencer': 'reportes.ver'}
    serializer_class = MembresiaSerializer

    def get_queryset(self):
        qs = (
            Membresia.objects.select_related('cliente', 'plan', 'sede', 'vendedor', 'entrenador')
            .order_by('-fecha_fin')
        )
        params = self.request.query_params

        cliente_id = params.get('cliente')
        if cliente_id:
            qs = qs.filter(cliente_id=cliente_id)

        sede_id = params.get('sede')
        if sede_id:
            qs = qs.filter(sede_id=sede_id)

        estado = params.get('estado')
        if estado:
            ids_con_estado = VistaMembresiaEstado.objects.filter(
                estado_calculado=estado,
            ).values_list('id', flat=True)
            qs = qs.filter(id__in=list(ids_con_estado))

        return qs

    def list(self, request, *args, **kwargs):
        # El estado calculado (RF-16) sale de v_membresias_estado; se trae
        # de UNA sola consulta para toda la página (no una por fila) y se
        # pasa al serializer vía contexto -- ver MembresiaSerializer._vista_estado.
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        objetos = page if page is not None else queryset

        estado_por_id = {
            vista.id: vista
            for vista in VistaMembresiaEstado.objects.filter(id__in=[m.id for m in objetos])
        }
        contexto = self.get_serializer_context()
        contexto['estado_por_id'] = estado_por_id
        serializer = self.get_serializer(objetos, many=True, context=contexto)

        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        entrada = AsignarMembresiaInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        cliente = Cliente.objects.filter(pk=datos['cliente_id']).first()
        if cliente is None:
            raise serializers.ValidationError({'cliente_id': 'Cliente no encontrado.'})

        plan = Plan.objects.filter(pk=datos['plan_id']).first()
        if plan is None:
            raise serializers.ValidationError({'plan_id': 'Plan no encontrado.'})

        sede = Sede.objects.filter(pk=datos['sede_id']).first()
        if sede is None:
            raise serializers.ValidationError({'sede_id': 'Sede no encontrada.'})

        try:
            membresia = asignar_membresia(
                tenant=request.tenant,
                sede=sede,
                cliente=cliente,
                plan=plan,
                vendedor=request.user,
                precio_pagado=datos['precio_pagado'],
                fecha_inicio=datos.get('fecha_inicio'),
                entrenador_id=datos.get('entrenador_id'),
            )
        except MembresiaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        salida = MembresiaSerializer(membresia, context=self.get_serializer_context())
        return Response(salida.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def renovar(self, request, pk=None):
        membresia_anterior = self.get_object()
        entrada = RenovarMembresiaInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        plan = None
        plan_id = datos.get('plan_id')
        if plan_id:
            plan = Plan.objects.filter(pk=plan_id).first()
            if plan is None:
                return Response(
                    {'plan_id': 'Plan no encontrado.'}, status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            membresia = renovar_membresia(
                membresia_anterior=membresia_anterior,
                usuario=request.user,
                precio_pagado=datos['precio_pagado'],
                plan=plan,
            )
        except MembresiaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        salida = MembresiaSerializer(membresia, context=self.get_serializer_context())
        return Response(salida.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        membresia = self.get_object()
        entrada = CancelarMembresiaInputSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        try:
            cancelar_membresia(
                membresia=membresia, usuario=request.user,
                motivo=entrada.validated_data['motivo'],
            )
        except MembresiaError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        membresia.refresh_from_db()
        salida = MembresiaSerializer(membresia, context=self.get_serializer_context())
        return Response(salida.data)

    @action(detail=False, methods=['get'], url_path='por-vencer')
    def por_vencer(self, request):
        """``GET /api/membresias/por-vencer/`` (``reportes.ver``, A5): las
        que vencen en los próximos N días (N = ``dias_aviso_vencimiento`` del
        tenant, ya aplicado por ``v_membresias_estado``) más las ya vencidas,
        ordenadas por ``fecha_fin``. Sin paginar: es un tablero de alertas,
        no un listado general (mismo criterio que ``/clientes/{id}/deuda/``).
        """
        vistas = list(
            VistaMembresiaEstado.objects.filter(
                estado_calculado__in=[
                    VistaMembresiaEstado.EstadoCalculado.VENCIDA,
                    VistaMembresiaEstado.EstadoCalculado.VENCE_HOY,
                    VistaMembresiaEstado.EstadoCalculado.POR_VENCER,
                ],
            ).order_by('fecha_fin')
        )
        membresias_por_id = {
            m.id: m
            for m in Membresia.objects.select_related('cliente', 'plan')
            .filter(id__in=[v.id for v in vistas])
        }

        filas = []
        for vista in vistas:
            membresia = membresias_por_id.get(vista.id)
            if membresia is None:
                continue
            filas.append({
                'id': vista.id,
                'cliente_id': membresia.cliente_id,
                'cliente_nombre': membresia.cliente.nombre,
                'cliente_telefono': membresia.cliente.telefono,
                'plan_id': membresia.plan_id,
                'plan_nombre': membresia.plan.nombre,
                'sede_id': vista.sede_id,
                'fecha_fin': vista.fecha_fin,
                'dias_restantes': vista.dias_restantes,
                'estado_calculado': vista.estado_calculado,
            })

        datos = MembresiaPorVencerSerializer(filas, many=True).data
        return Response(datos)


class PlanViewSet(viewsets.ModelViewSet):
    """``/api/planes/``: catálogo de planes vendibles (pantalla "Gestión de
    Membresías"). Antes lo servía ``apps.ventas.views.PlanListView`` (solo
    lectura); al pasar a CRUD se trasladó aquí, junto al modelo ``Plan``,
    conservando la misma URL, método y permiso para el POS y el alta de
    clientes (ver docstring de ``apps.ventas.urls``).

    El borrado (``DELETE``) es LÓGICO, no elimina la fila: ``Membresia.plan``
    es ``on_delete=PROTECT``, así que un borrado real reventaría en cuanto el
    plan tenga una sola membresía vendida, además de destruir el histórico de
    precios de esas membresías. Dar de baja el plan (``activo=False``) lo
    saca del catálogo vendible sin tocar nada de lo ya vendido.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'membresias.gestionar'
    serializer_class = PlanAdminSerializer

    def get_queryset(self):
        qs = Plan.objects.select_related('sede').order_by('nombre')

        # Filtro de compatibilidad, crítico: los consumidores existentes
        # (buscador del POS, alta de clientes) esperan exactamente el
        # comportamiento de la antigua PlanListView -- solo planes activos.
        # Únicamente la pantalla nueva de gestión pide ver también los
        # dados de baja (para poder reactivarlos), y lo hace explícito con
        # ?incluir_inactivos=1.
        #
        # El filtro es SOLO del listado. Aplicado también a las acciones de
        # detalle hacía que la baja lógica no tuviera vuelta atrás: reactivar
        # es un PATCH {activo: true} sobre una fila que está inactiva, y el
        # queryset la escondía, así que respondía 404.
        incluir_inactivos = self.request.query_params.get('incluir_inactivos', '').lower() in ('1', 'true')
        if self.action == 'list' and not incluir_inactivos:
            qs = qs.filter(activo=True)

        return qs

    def perform_create(self, serializer):
        # El tenant nunca se acepta desde el payload: lo impone el servidor
        # a partir del middleware multi-tenant (RLS), igual que en
        # apps.clientes.serializers.ClienteSerializer.create.
        serializer.save(tenant=self.request.tenant)

    def destroy(self, request, *args, **kwargs):
        plan = self.get_object()
        plan.activo = False
        plan.save(update_fields=['activo'])
        return Response(status=status.HTTP_204_NO_CONTENT)
