"""Facturación de las suscripciones: qué se cobra, a quién y cuándo.

Este módulo es el único sitio donde se decide un importe. Las vistas y el
comando de consola son dos puertas a las mismas funciones de aquí, igual que
pasa con el alta de gimnasios en ``aprovisionamiento``.

## Qué se cobra

``precio_por_sede × sedes activas``, según la decisión 13 del esquema. El
número de sedes se congela en la factura (``sedes_facturadas``): es una foto
del momento de emitir, no un dato que se recalcule después. Si el gimnasio
abre una sede el mes que viene, la factura de este mes no cambia — y eso es
lo correcto, porque ya se emitió y probablemente ya se envió.

## Nada es automático por sí solo

No hay ningún proceso que emita facturas ni que suspenda a nadie por su
cuenta. Estas funciones las dispara siempre alguien: un botón del panel o el
comando ``emitir_facturas``. Es una decisión deliberada: cobrar de más o
cortarle el servicio a un gimnasio en plena tarde son errores caros, y
conviene que haya una persona en el camino.
"""
import calendar
from datetime import date

from django.db import transaction

from apps.core.tenant import tenant_context
from apps.organizacion.models import Sede

from .models import FacturaSuscripcion, PlanSuscripcion, Suscripcion


class FacturacionError(Exception):
    """Fallo de negocio al facturar (sin sedes, periodo ya emitido...)."""


def sumar_ciclo(fecha, ciclo):
    """Suma un ciclo de facturación a ``fecha``.

    El caso que obliga a escribir esto a mano en vez de sumar 30 días: un
    cobro del 31 de enero. "Un mes después" no es el 31 de febrero, que no
    existe. Se recorta al último día del mes destino (28 de febrero), que es
    lo que hace cualquier facturación seria; sumar 30 días desplazaría la
    fecha de cobro un poco cada mes hasta acabar cobrando en otra semana.
    """
    if ciclo == PlanSuscripcion.CicloSuscripcion.ANUAL:
        anio, mes = fecha.year + 1, fecha.month
    else:
        anio, mes = (fecha.year + 1, 1) if fecha.month == 12 else (fecha.year, fecha.month + 1)

    ultimo_dia = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(fecha.day, ultimo_dia))


def sedes_activas(tenant_id):
    """Cuántas sedes activas tiene el gimnasio.

    ``sedes`` está bajo RLS, así que hay que entrar en su contexto: esta
    llamada viene del panel del proveedor, que no tiene ningún tenant fijado.
    """
    with tenant_context(tenant_id):
        return Sede.objects.filter(tenant_id=tenant_id, activa=True).count()


@transaction.atomic
def emitir_factura(suscripcion, hoy=None):
    """Emite la factura del periodo que arranca en ``proximo_corte``.

    Devuelve la ``FacturaSuscripcion`` creada y avanza ``proximo_corte`` al
    inicio del periodo siguiente, todo en la misma transacción: una factura
    emitida sin avanzar el corte se volvería a emitir en la siguiente pasada
    del comando, y un corte avanzado sin factura se saltaría un cobro.

    ``hoy`` se puede inyectar para poder probar el comportamiento en fechas
    concretas sin tocar el reloj del sistema.
    """
    hoy = hoy or date.today()

    if suscripcion.estado == Suscripcion.EstadoSuscripcion.CANCELADA:
        raise FacturacionError('La suscripción está cancelada: no se puede facturar.')

    periodo_inicio = suscripcion.proximo_corte
    if periodo_inicio > hoy:
        raise FacturacionError(
            f'El próximo corte de este gimnasio es el {periodo_inicio:%d/%m/%Y}. '
            'Todavía no hay nada que facturar.',
        )

    # La restricción `uq_facturas_periodo` ya lo impediría, pero un
    # IntegrityError sale como 500 y no explica nada.
    if suscripcion.facturas.filter(periodo_inicio=periodo_inicio).exists():
        raise FacturacionError(
            f'Ya existe una factura para el periodo que empieza el '
            f'{periodo_inicio:%d/%m/%Y}.',
        )

    plan = suscripcion.plan_suscripcion
    numero_sedes = sedes_activas(suscripcion.tenant_id)
    if numero_sedes == 0:
        # `ck_facturas_sedes` exige más de cero. Un gimnasio sin sedes activas
        # no está usando nada, así que cobrarle sería un error, no un caso a
        # resolver con un mínimo de uno.
        raise FacturacionError(
            'El gimnasio no tiene ninguna sede activa: no hay nada que cobrar. '
            'Revisa si debería estar suspendido o cancelado.',
        )

    periodo_fin = sumar_ciclo(periodo_inicio, plan.ciclo)

    factura = FacturaSuscripcion.objects.create(
        suscripcion=suscripcion,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        sedes_facturadas=numero_sedes,
        monto=plan.precio_por_sede * numero_sedes,
        fecha_emision=hoy,
    )

    suscripcion.proximo_corte = periodo_fin
    suscripcion.save(update_fields=['proximo_corte'])

    return factura


def facturas_vencidas(suscripcion, hoy=None):
    """Facturas emitidas cuyo plazo de gracia ya pasó y siguen sin pagar."""
    hoy = hoy or date.today()
    vencidas = []
    for factura in suscripcion.facturas.filter(
        estado=FacturaSuscripcion.EstadoFactura.EMITIDA,
    ):
        if (hoy - factura.fecha_emision).days > suscripcion.dias_gracia:
            vencidas.append(factura)
    return vencidas


def marcar_mora(suscripcion, hoy=None):
    """Pone la suscripción en mora si tiene facturas vencidas, o la devuelve a
    vigente si ya no las tiene. Devuelve ``True`` si cambió algo.

    Marca la SUSCRIPCIÓN, nunca el estado del tenant. Es la diferencia entre
    "este cliente me debe dinero" y "este gimnasio deja de funcionar": lo
    segundo apaga el negocio de alguien y se decide a mano, mirando el caso.

    Tampoco toca las canceladas: una suscripción terminada no vuelve sola a
    vigente porque alguien pagara una factura pendiente.
    """
    if suscripcion.estado == Suscripcion.EstadoSuscripcion.CANCELADA:
        return False

    debe = bool(facturas_vencidas(suscripcion, hoy))
    nuevo = (
        Suscripcion.EstadoSuscripcion.MORA if debe else Suscripcion.EstadoSuscripcion.VIGENTE
    )
    if suscripcion.estado == nuevo:
        return False

    suscripcion.estado = nuevo
    suscripcion.save(update_fields=['estado'])
    return True


@transaction.atomic
def marcar_pagada(factura, fecha_pago=None):
    """Registra el cobro de una factura.

    ``ck_facturas_pago`` obliga a que ``pagada`` y ``fecha_pago`` viajen
    juntas, así que se fijan a la vez; separarlas dejaría la fila en un
    estado que la base rechaza.
    """
    if factura.estado == FacturaSuscripcion.EstadoFactura.ANULADA:
        raise FacturacionError('La factura está anulada: no se puede cobrar.')
    if factura.estado == FacturaSuscripcion.EstadoFactura.PAGADA:
        raise FacturacionError('Esa factura ya estaba pagada.')

    factura.estado = FacturaSuscripcion.EstadoFactura.PAGADA
    factura.fecha_pago = fecha_pago or date.today()
    factura.save(update_fields=['estado', 'fecha_pago'])

    # Cobrar puede sacar al cliente de la mora, y esperar a la siguiente
    # pasada del comando dejaría marcado como moroso a quien acaba de pagar.
    marcar_mora(factura.suscripcion)
    return factura


@transaction.atomic
def anular_factura(factura):
    """Anula una factura emitida por error.

    No se borra: el histórico de facturación tiene que poder explicarse
    entero, incluidos los errores. Una factura ya pagada no se anula — eso
    sería una devolución, que es otra operación y no está modelada.
    """
    if factura.estado == FacturaSuscripcion.EstadoFactura.PAGADA:
        raise FacturacionError(
            'No se puede anular una factura ya pagada. Eso sería una '
            'devolución, y hoy no está contemplada.',
        )
    if factura.estado == FacturaSuscripcion.EstadoFactura.ANULADA:
        raise FacturacionError('Esa factura ya estaba anulada.')

    factura.estado = FacturaSuscripcion.EstadoFactura.ANULADA
    factura.save(update_fields=['estado'])

    marcar_mora(factura.suscripcion)
    return factura
