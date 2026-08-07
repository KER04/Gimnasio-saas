"""API de entrenamiento (RF-12): catálogo de ejercicios, rutinas y medidas.

## Quién puede

``rutinas.gestionar`` para el catálogo y las rutinas; ``medidas.gestionar``
para las fichas de medidas. El rol ``entrenador`` que siembra
``aprovisionamiento`` ya trae los dos.

Un entrenador ve y edita las rutinas y fichas de TODO el gimnasio, no solo
las suyas: en un gimnasio pequeño se cubren entre ellos cuando uno falta, y
acotarlo dejaría a un cliente sin poder entrenar porque su entrenador está de
vacaciones. Quién creó cada cosa queda guardado igualmente
(``rutinas.entrenador``, ``fichas_medidas.entrenador``).

## Lo que NO está

``registros_ejercicios`` (cada serie ejecutada) y ``records_personales``. Sus
tablas existen, pero se escriben "desde el celular, entre series" y en este
sistema el cliente no tiene acceso: lo teclearía el entrenador, que en la
práctica no lo hace. Además ``records_personales`` necesita un disparador que
todavía no existe. Ver la conversación de alcance de RF-12.
"""
from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response

from apps.core.fechas import hoy_de_la_peticion
from apps.core.permissions import TienePermiso

from .models import (
    ControlMedida,
    Ejercicio,
    FichaMedidas,
    GrupoMuscular,
    Rutina,
    RutinaDia,
    RutinaEjercicio,
)
from .serializers import (
    MEDIDAS,
    ControlMedidaSerializer,
    EjercicioSerializer,
    FichaMedidasSerializer,
    GrupoMuscularSerializer,
    RutinaSerializer,
)


def _quiere_inactivos(request):
    return request.query_params.get('incluir_inactivos', '') in ('1', 'true', 'True')


class GrupoMuscularListView(ListAPIView):
    """``GET /api/grupos-musculares/``: los siete que se siembran al crear el
    gimnasio (RF-12). Solo lectura: son la taxonomía sobre la que se ordena
    el catálogo, no algo que cada gimnasio deba inventarse."""

    permission_classes = [TienePermiso]
    permiso_requerido = 'rutinas.gestionar'
    serializer_class = GrupoMuscularSerializer

    def get_queryset(self):
        return GrupoMuscular.objects.order_by('orden', 'nombre')


class EjercicioViewSet(viewsets.ModelViewSet):
    """``/api/ejercicios/`` (``rutinas.gestionar``): el catálogo del gimnasio.

    Nace vacío: cada gimnasio arma el suyo. La baja es lógica porque
    ``RutinaEjercicio.ejercicio`` es ``PROTECT`` -- borrar un ejercicio usado
    dejaría rutinas antiguas sin poder explicarse.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'rutinas.gestionar'
    serializer_class = EjercicioSerializer

    def get_queryset(self):
        qs = Ejercicio.objects.select_related('grupo_muscular')
        # El filtro de activos solo aplica al LISTADO. Si aplicara también a
        # `retrieve`/`update`, un ejercicio dado de baja daría 404 al intentar
        # reactivarlo: la baja sería un viaje sin retorno.
        if self.action == 'list' and not _quiere_inactivos(self.request):
            qs = qs.filter(activo=True)
        grupo = self.request.query_params.get('grupo')
        if grupo:
            qs = qs.filter(grupo_muscular_id=grupo)
        buscar = self.request.query_params.get('buscar')
        if buscar:
            for termino in buscar.split():
                qs = qs.filter(nombre__icontains=termino)
        return qs.order_by('grupo_muscular__orden', 'nombre')

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)

    def destroy(self, request, *args, **kwargs):
        ejercicio = self.get_object()
        ejercicio.activo = False
        ejercicio.save(update_fields=['activo'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class RutinaViewSet(viewsets.ModelViewSet):
    """``/api/rutinas/`` (``rutinas.gestionar``).

    La rutina se guarda ENTERA, con sus días y sus ejercicios, en una sola
    petición y una sola transacción. Es un documento que el entrenador arma
    de una vez; partirlo en endpoints por día obligaría al frontend a
    orquestar diez llamadas y dejaría la rutina a medias si una fallara.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'rutinas.gestionar'
    serializer_class = RutinaSerializer

    def get_queryset(self):
        qs = (
            Rutina.objects
            .select_related('cliente', 'entrenador')
            .prefetch_related('dias__ejercicios__ejercicio__grupo_muscular')
        )
        # Igual que en el catálogo: solo el listado esconde las archivadas, o
        # no habría forma de reactivar una.
        if self.action == 'list' and self.request.query_params.get(
            'incluir_inactivas', '',
        ) not in ('1', 'true', 'True'):
            qs = qs.filter(activa=True)
        cliente = self.request.query_params.get('cliente')
        if cliente:
            qs = qs.filter(cliente_id=cliente)
        return qs.order_by('-fecha_inicio', '-id')

    def create(self, request, *args, **kwargs):
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dias = entrada.validated_data.pop('dias', [])

        with transaction.atomic():
            rutina = entrada.save(
                tenant_id=request.tenant_id,
                # El entrenador es QUIEN LA CREA, no un id del cuerpo: si
                # viniera de fuera se podrían atribuir rutinas a otro.
                entrenador=request.user,
                **({} if entrada.validated_data.get('fecha_inicio')
                   else {'fecha_inicio': hoy_de_la_peticion(request)}),
            )
            self._guardar_dias(rutina, dias)

        return Response(
            self.get_serializer(self._recargar(rutina)).data, status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        """Siempre parcial. Si vienen ``dias``, SUSTITUYEN a los que había.

        Se borra y se vuelve a crear en vez de calcular diferencias: un día
        de rutina no tiene nada que conservar más allá de lo que se envía, y
        casar altas, bajas y reordenaciones sería mucho código para ningún
        beneficio. Los registros de series ejecutadas colgarían de aquí
        cuando existan, y ese día habrá que reconsiderarlo.
        """
        rutina = self.get_object()
        entrada = self.get_serializer(rutina, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        dias = entrada.validated_data.pop('dias', None)

        with transaction.atomic():
            entrada.save()
            if dias is not None:
                rutina.dias.all().delete()
                self._guardar_dias(rutina, dias)

        return Response(self.get_serializer(self._recargar(rutina)).data)

    def _guardar_dias(self, rutina, dias):
        for dia_datos in dias:
            ejercicios = dia_datos.pop('ejercicios', [])
            dia = RutinaDia.objects.create(
                rutina=rutina, tenant_id=rutina.tenant_id, **dia_datos,
            )
            RutinaEjercicio.objects.bulk_create([
                RutinaEjercicio(rutina_dia=dia, tenant_id=rutina.tenant_id, **datos)
                for datos in ejercicios
            ])

    def _recargar(self, rutina):
        return self.get_queryset().model.objects.prefetch_related(
            'dias__ejercicios__ejercicio__grupo_muscular',
        ).select_related('cliente', 'entrenador').get(pk=rutina.pk)

    def destroy(self, request, *args, **kwargs):
        """Archiva la rutina en vez de borrarla: es el histórico de lo que ese
        cliente entrenó."""
        rutina = self.get_object()
        rutina.activa = False
        rutina.save(update_fields=['activa'])
        return Response(status=status.HTTP_204_NO_CONTENT)


class FichaMedidasViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """``/api/fichas-medidas/`` (``medidas.gestionar``).

    Un cliente tiene como mucho UNA ficha activa: lo impone
    ``uq_ficha_cliente_activa``. Empezar un proceso nuevo exige cerrar el
    anterior, y así el histórico queda por etapas en vez de mezclado.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'medidas.gestionar'
    serializer_class = FichaMedidasSerializer

    def get_queryset(self):
        qs = FichaMedidas.objects.select_related('cliente', 'entrenador').prefetch_related(
            'controles__registrado_por',
        )
        # Una ficha cerrada tiene que seguir siendo consultable: es el
        # histórico del proceso anterior de ese cliente.
        if self.action == 'list' and not _quiere_inactivos(self.request):
            qs = qs.filter(activa=True)
        cliente = self.request.query_params.get('cliente')
        if cliente:
            qs = qs.filter(cliente_id=cliente)
        return qs.order_by('-fecha_inicio', '-id')

    def perform_create(self, serializer):
        serializer.save(
            tenant_id=self.request.tenant_id,
            entrenador=self.request.user,
            # La fecha se manda EXPLÍCITA en la zona del gimnasio. Si se
            # dejara al `db_default=CURRENT_DATE`, una ficha abierta a las
            # ocho de la noche diría que empezó mañana (ver `apps.core.fechas`).
            **({} if serializer.validated_data.get('fecha_inicio')
               else {'fecha_inicio': hoy_de_la_peticion(self.request)}),
        )

    @action(detail=True, methods=['post'])
    def cerrar(self, request, pk=None):
        """Termina el proceso. No borra nada: los controles siguen ahí, y el
        cliente puede empezar otro."""
        ficha = self.get_object()
        ficha.activa = False
        ficha.save(update_fields=['activa'])
        return Response(self.get_serializer(ficha).data)

    @action(detail=True, methods=['post'], url_path='controles')
    def agregar_control(self, request, pk=None):
        """Registra una medición.

        El ``numero_control`` lo calcula el servidor: es el siguiente de la
        ficha. Dejarlo en manos del cliente HTTP invitaría a repetir un
        número y chocar con ``uq_control_numero``, y no aporta nada -- el
        orden de los controles es exactamente el orden en que se tomaron.
        """
        ficha = self.get_object()
        entrada = ControlMedidaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        with transaction.atomic():
            # `select_for_update` sobre la ficha: dos controles registrados a
            # la vez pedirían el mismo número siguiente.
            FichaMedidas.objects.select_for_update().get(pk=ficha.pk)
            ultimo = ficha.controles.order_by('-numero_control').first()
            control = entrada.save(
                tenant_id=ficha.tenant_id,
                ficha_medida=ficha,
                numero_control=(ultimo.numero_control + 1) if ultimo else 1,
                registrado_por=request.user,
                **({} if entrada.validated_data.get('fecha')
                   else {'fecha': hoy_de_la_peticion(request)}),
            )

        return Response(
            ControlMedidaSerializer(control).data, status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def comparativa(self, request, pk=None):
        """La vista para la que existe esta tabla: cada medida con su valor en
        cada control y la diferencia entre el primero y el último.

        Se pivota aquí y no en el cliente porque la pregunta que responde
        ("¿bajó el abdomen?") es por MEDIDA, mientras que los datos se
        guardan por CONTROL. Ver el docstring de ``ControlMedida`` sobre por
        qué se guardan así.
        """
        ficha = self.get_object()
        controles = list(ficha.controles.order_by('numero_control'))

        filas = []
        for medida in MEDIDAS:
            valores = [getattr(control, medida) for control in controles]
            # Primero y último NO NULOS: si en el control 3 no se tomó el
            # cuello, la diferencia debe seguir midiéndose entre las veces
            # que sí se tomó, no salir vacía.
            tomados = [v for v in valores if v is not None]
            diferencia = (tomados[-1] - tomados[0]) if len(tomados) >= 2 else None

            filas.append({
                'medida': medida,
                'valores': [str(v) if v is not None else None for v in valores],
                'diferencia': str(diferencia) if diferencia is not None else None,
            })

        return Response({
            'ficha': {
                'id': ficha.id,
                'cliente_nombre': ficha.cliente.nombre,
                'estatura_cm': str(ficha.estatura_cm) if ficha.estatura_cm else None,
            },
            'controles': [
                {
                    'id': c.id,
                    'numero_control': c.numero_control,
                    'fecha': c.fecha.isoformat(),
                    'edad': c.edad,
                }
                for c in controles
            ],
            'filas': filas,
        })
