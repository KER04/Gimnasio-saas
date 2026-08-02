"""Capa de servicio de asistencia (RF-15, sin la parte biométrica: el lector
ZK9500 todavía no llegó). Toda la lógica de negocio vive aquí; vistas y
serializers (``apps/asistencia/views.py``/``serializers.py``) solo traducen
HTTP <-> Python y delegan por completo en ``registrar_asistencia``, igual
que ``apps.ventas.services``/``apps.membresias.services`` para sus módulos.

``AsistenciaError`` (y sus dos subclases, ``AntipassbackError`` y
``AutorizacionError``) son las únicas excepciones que esta función lanza a
propósito para señalar una violación de una regla de NEGOCIO (nunca un
bug): la vista las atrapa y las traduce a 400/409/403 respectivamente, con
``str(exc)`` como mensaje, en español.
"""
import math

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.auditoria.models import Auditoria, VistaMembresiaEstado
from apps.auditoria.services import registrar_auditoria
from apps.core.permissions import usuario_tiene_permiso

from .models import Asistencia

# Estados de v_membresias_estado (RF-16) que cuentan como "vigente" para
# efectos de check-in: la membresía todavía no venció, sin importar si está
# a punto de hacerlo. 'vencida' y 'cancelada' NO cuentan.
_ESTADOS_VIGENTES = (
    VistaMembresiaEstado.EstadoCalculado.ACTIVA,
    VistaMembresiaEstado.EstadoCalculado.VENCE_HOY,
    VistaMembresiaEstado.EstadoCalculado.POR_VENCER,
)


class AsistenciaError(Exception):
    """Violación de una regla de negocio del módulo de asistencia. Se lanza
    deliberadamente (nunca es un bug); la vista la convierte en un 400 con
    ``str(exc)`` como mensaje."""


class AntipassbackError(AsistenciaError):
    """Se intentó un segundo ingreso del mismo cliente dentro de la ventana
    de antipassback del gimnasio. NO es un error del cliente ni un bug: es
    el comportamiento correcto (RF-15). La vista la traduce a 409, no a 400,
    para que quede claro que el sistema hizo justo lo que debía."""


class AutorizacionError(AsistenciaError):
    """Quien intenta autorizar un ingreso sin membresía vigente no tiene el
    permiso ``asistencia.autorizar``. La vista la traduce a 403."""


def _mensaje_limpio_postgres(exc):
    """Copia deliberadamente pequeña de la misma utilidad en
    ``apps.ventas.services``/``apps.membresias.services``: quedarse con la
    primera línea del mensaje de Postgres (sin el CONTEXT que antepone a un
    RAISE EXCEPTION o a un CHECK violado)."""
    texto = str(exc).strip()
    return texto.split('\n')[0].strip()


def cliente_tiene_membresia_vigente(cliente_id, using='default'):
    """``True`` si el cliente tiene AL MENOS UNA membresía cuyo estado
    calculado (``v_membresias_estado``, RF-16) sea 'activa', 'vence_hoy' o
    'por_vencer'. No recalcula el semáforo en Python: reutiliza la vista, tal
    como exige el encargo."""
    return (
        VistaMembresiaEstado.objects.using(using)
        .filter(cliente_id=cliente_id, estado_calculado__in=_ESTADOS_VIGENTES)
        .exists()
    )


def _resolver_sede_usuario(usuario, using='default'):
    """La sede de una asistencia sale del usuario autenticado, nunca del
    cuerpo de la petición (RF-15/A2.7): evita que un recepcionista registre
    ingresos "a nombre de" otra sede. Mismo criterio que
    ``apps.clientes.serializers._resolver_sede_origen``: si el usuario está
    asignado a exactamente una sede (``UsuarioSede``), se usa esa; si no hay
    ninguna o hay varias, no hay forma segura de adivinar."""
    from apps.organizacion.models import UsuarioSede

    sedes = list(
        UsuarioSede.objects.using(using).filter(usuario=usuario).values_list('sede_id', flat=True)
    )
    if len(sedes) == 1:
        return sedes[0]
    return None


def registrar_asistencia(
    *,
    tenant,
    usuario,
    metodo,
    cedula=None,
    venta_id=None,
    autorizado_por_id=None,
    motivo_autorizacion=None,
    using='default',
):
    """Registra un ingreso al gimnasio (RF-15, sin biometría).

    :param usuario: el usuario autenticado que opera el mostrador (de cuya
        sede sale ``sede_id``, no del cuerpo de la petición).
    :param metodo: ``Asistencia.MetodoAsistencia.MANUAL_CEDULA`` o
        ``SESION_ANONIMA``. ``HUELLA`` queda modelado pero no se acepta aquí
        todavía: el lector no existe.
    :param cedula: obligatoria si ``metodo='manual_cedula'``.
    :param venta_id: obligatoria si ``metodo='sesion_anonima'`` (CHECK
        ``ck_asist_anonima``: una sesión anónima siempre viene de una venta).
    :param autorizado_por_id: obligatorio si el cliente NO tiene membresía
        vigente (CHECK ``ck_asist_autorizacion``, decisión 12).
    :param motivo_autorizacion: obligatorio junto con ``autorizado_por_id``.
    :raises AsistenciaError: cualquier violación de una regla de negocio que
        no sea antipassback ni falta de permiso (ver subclases).
    :raises AntipassbackError: segundo ingreso del mismo cliente dentro de
        la ventana configurada (``tenant.minutos_antipassback``).
    :raises AutorizacionError: ``autorizado_por_id`` no tiene el permiso
        ``asistencia.autorizar``.
    """
    from apps.clientes.models import Cliente
    from apps.organizacion.models import Usuario
    from apps.ventas.models import Venta

    sede_id = _resolver_sede_usuario(usuario, using=using)
    if sede_id is None:
        raise AsistenciaError(
            'No se pudo determinar la sede del usuario autenticado: debe '
            'estar asignado a exactamente una sede para registrar ingresos.'
        )

    cliente = None
    venta = None

    if metodo == Asistencia.MetodoAsistencia.SESION_ANONIMA:
        if not venta_id:
            raise AsistenciaError(
                'Una sesión anónima exige indicar la venta de la sesión '
                'suelta (venta_id): se cobró la sesión pero no hay cliente '
                'identificado.'
            )
        venta = Venta.objects.using(using).filter(pk=venta_id).first()
        if venta is None:
            raise AsistenciaError('La venta indicada no existe.')
        con_membresia_vigente = False
    elif metodo == Asistencia.MetodoAsistencia.MANUAL_CEDULA:
        if not cedula:
            raise AsistenciaError('Debes indicar la cédula del cliente.')
        cliente = (
            Cliente.objects.using(using)
            .filter(cedula=cedula, eliminado_en__isnull=True)
            .first()
        )
        if cliente is None:
            raise AsistenciaError(f'No existe un cliente con la cédula "{cedula}".')
        con_membresia_vigente = cliente_tiene_membresia_vigente(cliente.id, using=using)
    else:
        raise AsistenciaError(
            f'Método de ingreso "{metodo}" no disponible: el lector de '
            'huella todavía no está instalado.'
        )

    autorizado_por = None
    motivo_final = None

    if cliente is not None and not con_membresia_vigente:
        # Decisión 12: sin membresía vigente, el ingreso exige autorización
        # nominal -- quién y por qué, no solo un booleano.
        if not autorizado_por_id or not motivo_autorizacion or not motivo_autorizacion.strip():
            raise AsistenciaError(
                f'{cliente.nombre} no tiene una membresía vigente: el '
                'ingreso exige indicar quién autoriza (autorizado_por_id) y '
                'el motivo (motivo_autorizacion).'
            )
        autorizado_por = Usuario.objects.using(using).filter(pk=autorizado_por_id).first()
        if autorizado_por is None:
            raise AsistenciaError('El usuario que autoriza no existe.')
        if not usuario_tiene_permiso(autorizado_por, 'asistencia.autorizar', using=using):
            raise AutorizacionError(
                f'"{autorizado_por.nombre}" no tiene el permiso '
                '"asistencia.autorizar" requerido para autorizar un ingreso '
                'sin membresía vigente.'
            )
        motivo_final = motivo_autorizacion

    # Antipassback (RF-15): solo aplica a clientes identificados -- una
    # sesión anónima no tiene "el mismo cliente" al que aplicarle la
    # ventana. Se mira la ÚLTIMA asistencia del cliente en CUALQUIER sede
    # (el índice ix_asist_cliente_fecha no filtra por sede): entrar por la
    # puerta de otra sede del mismo gimnasio dentro de la ventana también
    # cuenta como passback.
    if cliente is not None:
        ultima = (
            Asistencia.objects.using(using)
            .filter(cliente_id=cliente.id)
            .order_by('-fecha_hora')
            .first()
        )
        if ultima is not None:
            minutos_antipassback = tenant.minutos_antipassback
            transcurridos = (timezone.now() - ultima.fecha_hora).total_seconds() / 60
            if transcurridos < minutos_antipassback:
                faltan = max(1, math.ceil(minutos_antipassback - transcurridos))
                raise AntipassbackError(
                    f'{cliente.nombre} ya registró un ingreso hace '
                    f'{int(transcurridos)} minuto(s); debe esperar {faltan} '
                    'minuto(s) más antes de volver a entrar (antipassback). '
                    'No es un error: así se evita contar dos veces el mismo '
                    'ingreso.'
                )

    try:
        with transaction.atomic(using=using):
            asistencia = Asistencia.objects.using(using).create(
                tenant=tenant,
                sede_id=sede_id,
                cliente=cliente,
                venta=venta,
                metodo=metodo,
                con_membresia_vigente=con_membresia_vigente,
                autorizado_por=autorizado_por,
                motivo_autorizacion=motivo_final,
            )

            if autorizado_por is not None:
                # RF-02: autorizar un ingreso sin membresía vigente es una de
                # las operaciones que el requerimiento enumera explícitamente
                # como auditables.
                registrar_auditoria(
                    tenant_id=tenant.id,
                    usuario_id=usuario.id,
                    sede_id=sede_id,
                    entidad='asistencias',
                    entidad_id=asistencia.id,
                    accion=Auditoria.AccionAuditoria.AUTORIZAR,
                    valor_anterior=None,
                    valor_nuevo={
                        'cliente_id': cliente.id,
                        'autorizado_por': autorizado_por.id,
                        'motivo_autorizacion': motivo_final,
                    },
                    using=using,
                )
    except DatabaseError as exc:
        raise AsistenciaError(_mensaje_limpio_postgres(exc)) from exc

    return asistencia
