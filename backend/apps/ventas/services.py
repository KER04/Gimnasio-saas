"""Capa de servicio de ventas (Parte C del encargo). TODA la lógica de
negocio del POS vive aquí -- serializers y vistas (Parte D) solo traducen
HTTP <-> Python y delegan en estas funciones. Ninguna de ellas debe volver a
tomar una decisión de negocio (calcular estado, derivar categoría, decidir si
hay que renovar, etc.): eso es exactamente lo que este módulo existe para
centralizar.

Funciones públicas:

- ``registrar_venta(...)``: registra una venta completa (cabecera, líneas,
  movimientos de inventario, membresías, pago inicial) en una única
  transacción atómica.
- ``anular_venta(...)``: anula una venta existente, revirtiendo el
  inventario que haya movido y dejando traza en ``auditoria``.
- ``registrar_abono(...)``: registra un abono sobre una venta con saldo
  pendiente y recalcula su estado.

``VentaError`` es la única excepción que estas funciones lanzan a propósito
para señalar una violación de una regla de NEGOCIO (no un bug): la vista
(Parte D) la atrapa y la traduce a 400 con el mensaje tal cual, en español.
Cualquier error de base de datos que se escape (constraint violado, o el
``RAISE EXCEPTION`` del trigger de stock de la Parte B) también se traduce
aquí mismo a ``VentaError`` con un mensaje limpio, para que la vista nunca
tenga que lidiar con excepciones de psycopg/Django directamente.
"""
from decimal import Decimal

from django.db import DatabaseError, connections, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.auditoria.services import registrar_auditoria as _registrar_auditoria
from apps.membresias.models import Membresia, Plan
from apps.membresias.services import calcular_fechas_renovacion

from .models import CategoriaIngreso, DetalleVenta, Pago, Venta


class VentaError(Exception):
    """Violación de una regla de negocio del módulo de ventas.

    Se lanza deliberadamente (nunca es un bug) y la vista la convierte en un
    400 con ``str(exc)`` como mensaje. También es la excepción a la que se
    traduce cualquier ``DatabaseError`` que llegue desde Postgres (constraints,
    o el ``RAISE EXCEPTION`` de ``fn_actualizar_stock_sede``, Parte B), para
    que la vista nunca necesite conocer el vocabulario de la base de datos.
    """


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _mensaje_limpio_postgres(exc):
    """Postgres antepone contexto ('CONTEXT: PL/pgSQL function ...') al
    mensaje real de un RAISE EXCEPTION. Nos quedamos con la primera línea,
    que es exactamente el texto que escribimos en el trigger/función."""
    texto = str(exc).strip()
    return texto.split('\n')[0].strip()


def _siguiente_consecutivo(sede_id, using='default'):
    """Invoca ``fn_siguiente_consecutivo`` (apps.core migración 0001): hace
    ``UPDATE ... RETURNING`` sobre ``secuencias_comprobantes``, con bloqueo de
    fila implícito y sin huecos posibles ante un ROLLBACK (a diferencia de
    una SEQUENCE de Postgres, que no es transaccional -- ver el docstring de
    ``SecuenciaComprobante`` en ``apps/organizacion/models.py``)."""
    with connections[using].cursor() as cursor:
        cursor.execute('SELECT fn_siguiente_consecutivo(%s)', [sede_id])
        return cursor.fetchone()[0]


# RF-07: mapeo entre el tipo de plan y la subcategoría de ingreso "Planes"
# sembrada por `crear_tenant` (apps/plataforma/management/commands/crear_tenant.py).
_SUBCATEGORIA_INGRESO_POR_TIPO_PLAN = {
    Plan.TipoPlan.MENSUAL: 'Mensual',
    Plan.TipoPlan.QUINCENAL: 'Quincenal',
    Plan.TipoPlan.POR_SESION: 'Por sesión',
}


def _derivar_categoria_ingreso_producto(producto, tenant, using='default'):
    """RF-07: un producto se categoriza como 'Productos' / <nombre de su
    categoría de producto> (p. ej. 'Productos' / 'Suplementos'). Si el
    gimnasio tiene una categoría de producto con un nombre que no coincide
    con ninguna subcategoría de ingreso sembrada, se cae a 'Productos' /
    'Otros' en vez de reventar -- pero si ni siquiera esa existe, es un
    tenant mal sembrado y se rechaza con un mensaje claro."""
    nombre_subcategoria = producto.categoria_producto.nombre
    categoria = (
        CategoriaIngreso.objects.using(using)
        .filter(tenant=tenant, nombre='Productos', subcategoria=nombre_subcategoria)
        .first()
    )
    if categoria is None:
        categoria = (
            CategoriaIngreso.objects.using(using)
            .filter(tenant=tenant, nombre='Productos', subcategoria='Otros')
            .first()
        )
    if categoria is None:
        raise VentaError(
            'No existe una categoría de ingreso de productos configurada para '
            f'este gimnasio (ni "{nombre_subcategoria}" ni "Otros" bajo "Productos").'
        )
    return categoria


def _derivar_categoria_ingreso_plan(plan, tenant, using='default'):
    """RF-07: un plan con ``requiere_entrenador=True`` siempre cae en
    'Entrenamiento personalizado' (aunque sea, además, mensual/quincenal);
    el resto se categoriza por su ``tipo`` bajo 'Planes'."""
    if plan.requiere_entrenador:
        categoria = (
            CategoriaIngreso.objects.using(using)
            .filter(tenant=tenant, nombre='Entrenamiento personalizado')
            .first()
        )
        if categoria is None:
            raise VentaError(
                'No existe la categoría de ingreso "Entrenamiento personalizado" '
                'configurada para este gimnasio.'
            )
        return categoria

    subcategoria = _SUBCATEGORIA_INGRESO_POR_TIPO_PLAN[plan.tipo]
    categoria = (
        CategoriaIngreso.objects.using(using)
        .filter(tenant=tenant, nombre='Planes', subcategoria=subcategoria)
        .first()
    )
    if categoria is None:
        raise VentaError(
            f'No existe la categoría de ingreso "Planes / {subcategoria}" '
            'configurada para este gimnasio.'
        )
    return categoria


# ---------------------------------------------------------------------------
# C1. registrar_venta
# ---------------------------------------------------------------------------

def registrar_venta(
    *,
    tenant,
    sede,
    usuario,
    items,
    cliente=None,
    descuento=None,
    motivo_descuento=None,
    forma_pago=None,
    monto_pago_inicial=None,
    fecha_inicio_membresia=None,
    using='default',
):
    """Registra una venta completa en una única transacción atómica.

    :param items: lista de dicts, uno por línea. Cada uno trae:
        - ``tipo_item``: ``DetalleVenta.TipoItemVenta.PRODUCTO`` o ``PLAN``.
        - ``producto`` (instancia ``Producto``, si es producto) o ``plan``
          (instancia ``Plan``, si es plan).
        - ``cantidad`` (``Decimal``, > 0).
        - ``entrenador_id`` (opcional, solo planes con ``requiere_entrenador``).
        - ``descripcion`` (opcional: si no viene, se usa el nombre del
          producto/plan tal como está en el catálogo AHORA mismo).
    :param cliente: instancia ``Cliente`` o ``None`` (venta anónima).
    :param descuento: monto de descuento sobre el subtotal (``Decimal``).
    :param motivo_descuento: obligatorio si ``descuento > 0``.
    :param forma_pago: ``Pago.FormaPago``, obligatorio si hay pago inicial.
    :param monto_pago_inicial: dinero recibido en el momento de la venta.
    :param fecha_inicio_membresia: fecha desde la que empiezan a contarse las
        membresías nuevas (por defecto, hoy). Una renovación anticipada
        (RF-16) IGNORA este valor como punto de partida real y encadena
        desde la ``fecha_fin`` de la membresía vigente, no desde aquí.
    :raises VentaError: ante cualquier violación de una regla de negocio,
        con mensaje en español listo para mostrar.
    :return: la ``Venta`` creada, con sus ``detalles``/``pagos`` ya en base.
    """
    if not items:
        raise VentaError('La venta debe tener al menos un ítem.')

    descuento = descuento if descuento is not None else Decimal('0')
    monto_pago_inicial = monto_pago_inicial if monto_pago_inicial is not None else Decimal('0')
    fecha_inicio_membresia = fecha_inicio_membresia or timezone.localdate()

    if descuento > 0 and not (motivo_descuento and motivo_descuento.strip()):
        raise VentaError('Todo descuento mayor a cero exige indicar un motivo.')
    if descuento < 0:
        raise VentaError('El descuento no puede ser negativo.')

    # -----------------------------------------------------------------
    # Validación y preparación de líneas ANTES de tocar la base: si algo
    # aquí falla, no se ha gastado ni un consecutivo ni abierto ninguna
    # transacción todavía.
    # -----------------------------------------------------------------
    subtotal = Decimal('0')
    lineas = []
    requiere_cliente_por_membresia = False

    for item in items:
        cantidad = item.get('cantidad')
        if cantidad is None or cantidad <= 0:
            raise VentaError('La cantidad de cada ítem debe ser mayor que cero.')

        tipo_item = item['tipo_item']
        if tipo_item == DetalleVenta.TipoItemVenta.PRODUCTO:
            producto = item['producto']
            precio_unitario = producto.precio_venta
            costo_unitario = producto.costo
            categoria = _derivar_categoria_ingreso_producto(producto, tenant, using=using)
            lineas.append({
                'tipo_item': tipo_item,
                'producto': producto,
                'plan': None,
                'categoria_ingreso': categoria,
                'descripcion': item.get('descripcion') or producto.nombre,
                'cantidad': cantidad,
                'precio_unitario': precio_unitario,
                'costo_unitario': costo_unitario,
            })
        elif tipo_item == DetalleVenta.TipoItemVenta.PLAN:
            plan = item['plan']
            if plan.tipo != Plan.TipoPlan.POR_SESION and cantidad != 1:
                raise VentaError(
                    'Los planes con vigencia se venden de a una unidad por línea '
                    '(una membresía por línea de venta).'
                )
            precio_unitario = plan.precio
            categoria = _derivar_categoria_ingreso_plan(plan, tenant, using=using)
            lineas.append({
                'tipo_item': tipo_item,
                'producto': None,
                'plan': plan,
                'categoria_ingreso': categoria,
                'descripcion': item.get('descripcion') or plan.nombre,
                'cantidad': cantidad,
                'precio_unitario': precio_unitario,
                'costo_unitario': Decimal('0'),
                'entrenador_id': item.get('entrenador_id'),
            })
            if plan.tipo != Plan.TipoPlan.POR_SESION:
                requiere_cliente_por_membresia = True
        else:
            raise VentaError(f'Tipo de ítem de venta desconocido: "{tipo_item}".')

        subtotal += cantidad * precio_unitario

    if descuento > subtotal:
        raise VentaError('El descuento no puede ser mayor que el subtotal.')

    total = subtotal - descuento

    if requiere_cliente_por_membresia and cliente is None:
        # Regla adicional a la de "venta a crédito" (decisión 5): una
        # membresía SIEMPRE requiere un cliente (Membresia.cliente no admite
        # NULL, y con razón: ¿de quién sería la membresía?), sin importar si
        # la venta se paga de contado o no.
        raise VentaError('Vender un plan con vigencia exige un cliente identificado.')

    if monto_pago_inicial < 0:
        raise VentaError('El pago inicial no puede ser negativo.')
    if monto_pago_inicial > total:
        raise VentaError('El pago inicial no puede superar el total de la venta.')
    if monto_pago_inicial > 0 and not forma_pago:
        raise VentaError('Debes indicar la forma de pago del pago inicial.')

    if monto_pago_inicial >= total and total > 0:
        estado = Venta.EstadoVenta.PAGADA
    elif total == 0:
        # Venta en cero (p. ej. un plan regalado, precio cero): no hay nada
        # que cobrar, se considera pagada de inmediato.
        estado = Venta.EstadoVenta.PAGADA
    elif monto_pago_inicial > 0:
        estado = Venta.EstadoVenta.PARCIAL
    else:
        estado = Venta.EstadoVenta.PENDIENTE

    if estado in (Venta.EstadoVenta.PARCIAL, Venta.EstadoVenta.PENDIENTE) and cliente is None:
        # Decisión 5: venta anónima permitida, crédito no.
        raise VentaError(
            'Una venta con saldo pendiente (parcial o pendiente) exige un '
            'cliente identificado: no se puede fiar a un desconocido.'
        )

    try:
        with transaction.atomic(using=using):
            consecutivo = _siguiente_consecutivo(sede.id, using=using)

            venta = Venta.objects.using(using).create(
                tenant=tenant,
                sede=sede,
                cliente=cliente,
                usuario=usuario,
                consecutivo=consecutivo,
                subtotal=subtotal,
                descuento=descuento,
                total=total,
                motivo_descuento=motivo_descuento if descuento > 0 else None,
                estado=estado,
            )

            for linea in lineas:
                DetalleVenta.objects.using(using).create(
                    tenant=tenant,
                    venta=venta,
                    tipo_item=linea['tipo_item'],
                    producto=linea['producto'],
                    plan=linea['plan'],
                    categoria_ingreso=linea['categoria_ingreso'],
                    descripcion=linea['descripcion'],
                    cantidad=linea['cantidad'],
                    precio_unitario=linea['precio_unitario'],
                    costo_unitario=linea['costo_unitario'],
                )

                if linea['tipo_item'] == DetalleVenta.TipoItemVenta.PRODUCTO:
                    _registrar_salida_venta(
                        tenant=tenant, sede=sede, usuario=usuario, venta=venta,
                        producto=linea['producto'], cantidad=linea['cantidad'], using=using,
                    )
                else:
                    _registrar_membresia_si_aplica(
                        tenant=tenant, sede=sede, usuario=usuario, venta=venta,
                        cliente=cliente, plan=linea['plan'],
                        precio_pagado=linea['precio_unitario'],
                        entrenador_id=linea.get('entrenador_id'),
                        fecha_inicio_solicitada=fecha_inicio_membresia,
                        using=using,
                    )

            if monto_pago_inicial > 0:
                Pago.objects.using(using).create(
                    tenant=tenant,
                    venta=venta,
                    usuario=usuario,
                    monto=monto_pago_inicial,
                    forma_pago=forma_pago,
                    es_pago_inicial=True,
                )

            if descuento > 0:
                # RF-02: la aplicación de un descuento queda en auditoría.
                _registrar_auditoria(
                    tenant_id=tenant.id,
                    usuario_id=usuario.id,
                    sede_id=sede.id,
                    entidad='ventas',
                    entidad_id=venta.id,
                    accion=Auditoria.AccionAuditoria.CREAR,
                    valor_anterior=None,
                    valor_nuevo={
                        'descuento': str(descuento),
                        'motivo_descuento': motivo_descuento,
                        'subtotal': str(subtotal),
                        'total': str(total),
                    },
                    using=using,
                )
    except DatabaseError as exc:
        # Aquí llega, entre otras cosas, el RAISE EXCEPTION de
        # fn_actualizar_stock_sede (Parte B) cuando el stock es insuficiente:
        # el `with transaction.atomic` de arriba ya revirtió TODO (consecutivo
        # incluido) para cuando llegamos aquí -- no queda ninguna venta a medias.
        raise VentaError(_mensaje_limpio_postgres(exc)) from exc

    return venta


def _registrar_salida_venta(*, tenant, sede, usuario, venta, producto, cantidad, using):
    """Crea el movimiento de inventario de la venta de un producto. La
    cantidad se guarda en NEGATIVO (sale del inventario); el trigger de la
    Parte B (``fn_actualizar_stock_sede``) descuenta ``stock_sedes`` y
    rellena ``saldo_resultante`` -- o revierte TODA la venta si no hay
    existencia suficiente."""
    from apps.inventario.models import MovimientoInventario

    MovimientoInventario.objects.using(using).create(
        tenant=tenant,
        producto=producto,
        sede=sede,
        usuario=usuario,
        tipo=MovimientoInventario.TipoMovimiento.SALIDA_VENTA,
        cantidad=-cantidad,
        # El trigger de la Parte B sobrescribe este valor antes del INSERT
        # real (es un trigger BEFORE); el 0 de aquí nunca llega a persistirse.
        saldo_resultante=Decimal('0'),
        costo_unitario=producto.costo,
        venta=venta,
    )


def _registrar_membresia_si_aplica(
    *, tenant, sede, usuario, venta, cliente, plan, precio_pagado,
    entrenador_id, fecha_inicio_solicitada, using,
):
    """Crea la ``Membresia`` de un plan con vigencia (decisión 4: los planes
    ``por_sesion`` NUNCA generan membresía, son una venta suelta).

    Renovación (RF-16): si el cliente ya tiene una membresía ACTIVA del
    MISMO plan cuya ``fecha_fin`` todavía no pasó (>= fecha de inicio
    solicitada), la nueva membresía no arranca hoy: arranca justo donde
    terminaba la anterior, para no perder días ya pagados, y queda enlazada
    vía ``membresia_anterior``. Si la anterior ya venció, no hay nada que
    "encadenar": arranca de cero en la fecha solicitada.
    """
    if plan.tipo == Plan.TipoPlan.POR_SESION:
        return None

    membresia_anterior = (
        Membresia.objects.using(using)
        .filter(
            tenant=tenant,
            cliente=cliente,
            plan=plan,
            estado=Membresia.EstadoMembresia.ACTIVA,
            fecha_fin__gte=fecha_inicio_solicitada,
        )
        .order_by('-fecha_fin')
        .first()
    )

    # El cálculo de encadenado (RF-16) vive en un único lugar
    # (``apps.membresias.services.calcular_fechas_renovacion``), reutilizado
    # aquí y desde ``apps.membresias.services.renovar_membresia`` (endpoint
    # dedicado ``POST /api/membresias/{id}/renovar/``): si esta cuenta
    # divergiera entre los dos sitios, un cliente perdería días ya pagados
    # sin que nadie lo note.
    nueva_fecha_inicio, nueva_fecha_fin = calcular_fechas_renovacion(
        membresia_anterior=membresia_anterior,
        plan=plan,
        fecha_referencia=fecha_inicio_solicitada,
    )

    return Membresia.objects.using(using).create(
        tenant=tenant,
        cliente=cliente,
        plan=plan,
        sede=sede,
        venta=venta,
        entrenador_id=entrenador_id,
        vendedor=usuario,
        fecha_inicio=nueva_fecha_inicio,
        fecha_fin=nueva_fecha_fin,
        precio_pagado=precio_pagado,
        membresia_anterior=membresia_anterior,
    )


# ---------------------------------------------------------------------------
# C2. anular_venta
# ---------------------------------------------------------------------------

def anular_venta(*, venta, usuario, motivo, using='default'):
    """Anula una venta: NUNCA la borra (queda con ``estado='anulada'`` para
    siempre), revierte el inventario que haya movido, cancela las membresías
    que nacieron de ella y deja traza en ``auditoria``.

    Sobre las membresías: si la venta se anula, el acceso que pagó también
    tiene que caer. Dejarla activa significaba que anular la venta de un plan
    regalaba el mes al cliente -- el dinero se revierte pero el servicio no.
    Se cancelan siempre, con el motivo apuntando a la venta anulada; si el
    gimnasio decide cobrar los días ya usados, esa es una operación aparte y
    deliberada, no un efecto secundario de la anulación.

    :raises VentaError: si falta el motivo o la venta ya estaba anulada.
    """
    if not motivo or not motivo.strip():
        raise VentaError('Anular una venta exige indicar un motivo.')

    if venta.estado == Venta.EstadoVenta.ANULADA:
        raise VentaError('Esta venta ya está anulada; no se puede anular dos veces.')

    from apps.inventario.models import MovimientoInventario

    estado_anterior = venta.estado

    try:
        with transaction.atomic(using=using):
            detalles = list(
                venta.detalles.using(using).select_related('producto').all()
            )
            for detalle in detalles:
                if detalle.tipo_item == DetalleVenta.TipoItemVenta.PRODUCTO:
                    # Reverso con cantidad POSITIVA: entra de vuelta al
                    # inventario. El trigger de la Parte B suma el stock y
                    # rellena saldo_resultante igual que en cualquier otro
                    # movimiento -- este SIEMPRE puede aplicarse (una
                    # reversión nunca deja stock negativo).
                    MovimientoInventario.objects.using(using).create(
                        tenant=venta.tenant,
                        producto=detalle.producto,
                        sede=venta.sede,
                        usuario=usuario,
                        tipo=MovimientoInventario.TipoMovimiento.REVERSO_ANULACION,
                        cantidad=detalle.cantidad,
                        saldo_resultante=Decimal('0'),
                        costo_unitario=detalle.costo_unitario,
                        venta=venta,
                    )

            # Las membresías que nació de esta venta pierden su respaldo: si
            # la venta no vale, el acceso tampoco. Se deja constancia una por
            # una en la auditoría, porque revocar el acceso de un cliente es
            # una operación sensible que alguien puede tener que justificar.
            from apps.membresias.models import Membresia

            membresias = list(
                Membresia.objects.using(using)
                .filter(venta=venta)
                .exclude(estado=Membresia.EstadoMembresia.CANCELADA)
            )
            for membresia in membresias:
                estado_previo = membresia.estado
                membresia.estado = Membresia.EstadoMembresia.CANCELADA
                membresia.motivo_cancelacion = (
                    f'Venta {venta.consecutivo} anulada: {motivo}'
                )
                membresia.save(
                    using=using, update_fields=['estado', 'motivo_cancelacion'],
                )
                _registrar_auditoria(
                    tenant_id=venta.tenant_id,
                    usuario_id=usuario.id,
                    sede_id=venta.sede_id,
                    entidad='membresias',
                    entidad_id=membresia.id,
                    accion=Auditoria.AccionAuditoria.ANULAR,
                    valor_anterior={'estado': str(estado_previo)},
                    valor_nuevo={
                        'estado': str(Membresia.EstadoMembresia.CANCELADA),
                        'motivo_cancelacion': membresia.motivo_cancelacion,
                    },
                    using=using,
                )

            venta.estado = Venta.EstadoVenta.ANULADA
            venta.anulada_por = usuario
            venta.motivo_anulacion = motivo
            venta.anulada_en = timezone.now()
            venta.save(
                using=using,
                update_fields=['estado', 'anulada_por', 'motivo_anulacion', 'anulada_en'],
            )

            _registrar_auditoria(
                tenant_id=venta.tenant_id,
                usuario_id=usuario.id,
                sede_id=venta.sede_id,
                entidad='ventas',
                entidad_id=venta.id,
                accion=Auditoria.AccionAuditoria.ANULAR,
                valor_anterior={'estado': str(estado_anterior)},
                valor_nuevo={
                    'estado': str(Venta.EstadoVenta.ANULADA),
                    'motivo_anulacion': motivo,
                    'membresias_canceladas': [m.id for m in membresias],
                },
                using=using,
            )
    except DatabaseError as exc:
        raise VentaError(_mensaje_limpio_postgres(exc)) from exc

    return venta


# ---------------------------------------------------------------------------
# C3. registrar_abono
# ---------------------------------------------------------------------------

def registrar_abono(*, venta, usuario, monto, forma_pago, using='default'):
    """Registra un abono (RF-09). Recalcula el estado de la venta: pasa a
    ``pagada`` automáticamente al llegar a saldo cero.

    :raises VentaError: venta anulada, monto inválido, o abono mayor que el
        saldo pendiente.
    """
    if venta.estado == Venta.EstadoVenta.ANULADA:
        raise VentaError('No se puede abonar a una venta anulada.')
    if monto is None or monto <= 0:
        raise VentaError('El monto del abono debe ser mayor que cero.')
    if not forma_pago:
        raise VentaError('Debes indicar la forma de pago del abono.')

    try:
        with transaction.atomic(using=using):
            total_pagado = (
                Pago.objects.using(using)
                .filter(venta=venta, anulado=False)
                .aggregate(total=Sum('monto'))['total']
                or Decimal('0')
            )
            saldo = venta.total - total_pagado

            if monto > saldo:
                raise VentaError(
                    f'El abono (${monto}) no puede superar el saldo pendiente (${saldo}).'
                )

            pago = Pago.objects.using(using).create(
                tenant=venta.tenant,
                venta=venta,
                usuario=usuario,
                monto=monto,
                forma_pago=forma_pago,
                es_pago_inicial=False,
            )

            nuevo_saldo = saldo - monto
            if nuevo_saldo <= 0:
                venta.estado = Venta.EstadoVenta.PAGADA
            elif venta.estado == Venta.EstadoVenta.PENDIENTE:
                venta.estado = Venta.EstadoVenta.PARCIAL
            venta.save(using=using, update_fields=['estado'])
    except DatabaseError as exc:
        raise VentaError(_mensaje_limpio_postgres(exc)) from exc

    return pago
