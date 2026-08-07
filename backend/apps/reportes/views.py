"""Informes de caja, ventas e inventario (RF-08).

App sin modelos: todo lo que hay aquí son AGREGADOS sobre tablas y vistas que
ya existen. No se guarda ni un dato nuevo.

## Los dos totales que no son el mismo

Un "total de ventas" puede querer decir dos cosas distintas, y confundirlas
descuadra la caja:

- **Facturado**: la suma de ``ventas.total``, lo que se vendió.
- **Cobrado**: la suma de ``pagos.monto``, lo que realmente entró.

Desde que existen los abonos (RF-09) esos dos números divergen: una venta a
crédito suma al primero y no al segundo. Los informes devuelven SIEMPRE los
dos, y su diferencia, en vez de elegir uno y llamarlo "ventas".

## Zona horaria

TODOS los informes usan la zona horaria del GIMNASIO
(``tenants.zona_horaria``), no la del servidor.

El corte de caja lo hacía ya por su cuenta: sale de ``v_corte_diario``, que
agrupa por la fecha convertida en SQL. Los demás filtraban con ``__date``,
que usa ``settings.TIME_ZONE``, y coincidían solo porque todos los gimnasios
estaban en ``America/Bogota``. Desde que el panel del proveedor permite
cambiarle la zona a cada uno, esa coincidencia dejó de estar garantizada: un
gimnasio en otro huso habría visto sus ventas de después de las 19:00
contadas en el día siguiente, discrepando de su propio corte de caja por un
día justo en las horas de más afluencia. Ver ``_filtrar_fechas``.

## Anuladas

Se excluyen en los tres informes: una venta anulada no se vendió, y un pago
anulado no entró. La vista de corte ya lo hace por su cuenta.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings

from django.db.models import Count, DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.models import VistaCorteDiario, VistaVentaSaldo
from apps.clientes.models import Cliente
from apps.core.permissions import TienePermiso
from apps.core.sedes import acotar_por_sede, sedes_visibles
from apps.inventario.models import StockSede
from apps.ventas.models import DetalleVenta, Gasto, Pago, Venta


def _porcentaje(parte, total):
    """Porcentaje con un decimal, como texto. `'—'` cuando no hay base sobre
    la que calcular: un margen del 0% y "no hubo ventas" no son lo mismo."""
    if not total:
        return '—'
    return f'{(parte / total * 100):.1f}'

#: Cero decimal para que `Coalesce` no devuelva `None` en un periodo vacío:
#: un informe sin ventas debe decir 0, no dejar el hueco en blanco.
_CERO = Value(0, output_field=DecimalField(max_digits=14, decimal_places=2))


def _rango(request):
    """Lee ``?desde=`` y ``?hasta=`` (``YYYY-MM-DD``). Ambos opcionales."""
    return request.query_params.get('desde'), request.query_params.get('hasta')


def _zona_del_gimnasio(request):
    """La zona horaria del gimnasio de la petición, o la del servidor si no
    se puede resolver (``request.tenant`` siempre existe en estas vistas,
    pero fallar aquí no debe tumbar un informe)."""
    tenant = getattr(request, 'tenant', None)
    return getattr(tenant, 'zona_horaria', None) or settings.TIME_ZONE


def _filtrar_fechas(qs, campo, desde, hasta, zona):
    """Filtra por rango de fechas convirtiendo el instante a la zona del
    GIMNASIO, no a la del servidor.

    ``__date`` usa por defecto ``settings.TIME_ZONE``. Mientras todos los
    gimnasios estuvieran en la misma zona daba igual, pero desde que el panel
    del proveedor permite cambiársela a cada uno, esa suposición se rompe: un
    gimnasio en otro huso vería sus ventas de después de las 19:00 contadas
    en el día siguiente, mientras que su corte de caja
    (``v_corte_diario``, que sí usa ``tenants.zona_horaria``) las contaría en
    el día correcto. Los dos informes discreparían por un día justo en las
    horas de más afluencia.
    """
    if desde:
        qs = qs.filter(**{f'{campo}__gte': _inicio_del_dia(desde, zona)})
    if hasta:
        # El día `hasta` va INCLUIDO: el límite es la medianoche del día
        # siguiente, sin llegar a ella.
        qs = qs.filter(**{f'{campo}__lt': _inicio_del_dia(hasta, zona) + timedelta(days=1)})
    return qs


def _inicio_del_dia(fecha, zona):
    """Medianoche de ``fecha`` en la zona ``zona``, como instante absoluto.

    Se compara contra el timestamp crudo en vez de usar ``__date``: así el
    límite del rango es exactamente el que vive el gimnasio, sin depender de
    la zona con la que Django hable con la base de datos.
    """
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha)
    return datetime.combine(fecha, time.min, tzinfo=ZoneInfo(zona))


class ReporteVentasView(APIView):
    """``GET /api/reportes/ventas/?desde&hasta&sede`` (``reportes.ver``).

    Resumen de facturación: cuánto se vendió, cuánto se cobró y cuánto queda
    por cobrar, más el desglose por estado de cobro.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'reportes.ver'

    def get(self, request):
        desde, hasta = _rango(request)
        zona = _zona_del_gimnasio(request)

        ventas = acotar_por_sede(
            request, Venta.objects.exclude(estado=Venta.EstadoVenta.ANULADA),
        )
        ventas = _filtrar_fechas(ventas, 'fecha_hora', desde, hasta, zona)

        agregado = ventas.aggregate(
            facturado=Coalesce(Sum('total'), _CERO),
            descuentos=Coalesce(Sum('descuento'), _CERO),
            numero=Count('id'),
        )

        # El cobro se mide sobre PAGOS, no sobre el estado de la venta: es la
        # única fuente de caja real (misma decisión que toma v_corte_diario).
        pagos = Pago.objects.filter(anulado=False).exclude(
            venta__estado=Venta.EstadoVenta.ANULADA,
        )
        pagos = acotar_por_sede(request, pagos, campo='venta__sede_id')
        pagos = _filtrar_fechas(pagos, 'fecha_hora', desde, hasta, zona)
        cobrado = pagos.aggregate(total=Coalesce(Sum('monto'), _CERO))['total']

        por_estado = {
            fila['estado']: {'numero': fila['numero'], 'total': str(fila['total'])}
            for fila in ventas.values('estado').annotate(
                numero=Count('id'), total=Coalesce(Sum('total'), _CERO),
            )
        }

        return Response({
            'facturado': str(agregado['facturado']),
            'cobrado': str(cobrado),
            # Ojo: esta resta compara lo facturado EN EL RANGO con lo cobrado
            # EN EL RANGO. Un abono de hoy sobre una venta del mes pasado
            # entra en `cobrado` y no en `facturado`, así que la diferencia
            # puede salir negativa: es correcto, no es un error de cálculo.
            'diferencia': str(agregado['facturado'] - cobrado),
            'descuentos': str(agregado['descuentos']),
            'numero_ventas': agregado['numero'],
            'por_estado': por_estado,
        })


class ReporteCajaView(APIView):
    """``GET /api/reportes/caja/?desde&hasta&sede&agrupar=dia|mes``
    (``reportes.ver``).

    Dinero recibido, agrupado por día o por mes. Se apoya en
    ``v_corte_diario``, que ya resuelve lo difícil: la fecha en la zona
    horaria del gimnasio, el desglose por forma de pago, los ingresos que no
    vienen de ventas, y la exclusión de anuladas.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'reportes.ver'

    def get(self, request):
        desde, hasta = _rango(request)
        # Sin `zona` a propósito: `v_corte_diario` ya agrupa por la fecha
        # convertida a la del gimnasio, y aquí se filtra sobre esa columna
        # DATE ya resuelta.
        agrupar = request.query_params.get('agrupar', 'dia')

        qs = acotar_por_sede(request, VistaCorteDiario.objects.all())
        if desde:
            qs = qs.filter(fecha__gte=desde)
        if hasta:
            qs = qs.filter(fecha__lte=hasta)

        campos = ('ingreso_ventas', 'ingreso_otros', 'efectivo', 'transferencia', 'tarjeta', 'total_recibido')
        sumas = {campo: Coalesce(Sum(campo), _CERO) for campo in campos}

        if agrupar == 'mes':
            # Se agrupan las filas diarias; la vista ya las dejó en la zona
            # horaria correcta, así que truncar por mes aquí es seguro.
            filas = qs.annotate(periodo=TruncMonth('fecha')).values('periodo').annotate(**sumas).order_by('periodo')
        else:
            filas = qs.values(periodo=F('fecha')).annotate(**sumas).order_by('periodo')

        resultado = [
            {
                'periodo': str(fila['periodo']),
                **{campo: str(fila[campo]) for campo in campos},
            }
            for fila in filas
        ]
        totales = qs.aggregate(**sumas)

        return Response({
            'agrupar': 'mes' if agrupar == 'mes' else 'dia',
            'periodos': resultado,
            'totales': {campo: str(totales[campo]) for campo in campos},
        })


class ReporteUtilidadView(APIView):
    """``GET /api/reportes/utilidad/?desde&hasta&sede`` (``costos.ver``).

    Qué se ganó con lo vendido, producto a producto.

    ## Por qué exige ``costos.ver`` y no ``reportes.ver``

    Es el permiso que separa a quien puede ver márgenes de quien no (§2.1):
    el resto de la API borra ``costo`` y ``costo_unitario`` de sus respuestas
    a quien no lo tenga, y este informe no es más que esos costos agregados.
    Dejarlo en ``reportes.ver`` sería una puerta trasera al mismo dato.

    ## Cuenta al VENDER, no al cobrar (devengo)

    Una venta fiada suma aquí desde el momento en que se hace, aunque no haya
    entrado un peso. No es un descuido:

    - **El costo ya salió.** El producto dejó el inventario en el momento de
      la venta. Si el ingreso esperase al cobro pero el costo no, el periodo
      de la venta mostraría una pérdida inventada y el del cobro una ganancia
      igual de inventada. Los dos lados de ``ingresos - costo`` tienen que
      medirse en el mismo instante, y el único que ambos comparten es la
      venta.
    - **La visión de caja ya existe aparte**: ``/api/reportes/caja/`` suma
      pagos recibidos, y ``/api/reportes/ventas/`` da facturado y cobrado por
      separado. No hacía falta un tercer criterio, hacía falta decir cuál usa
      cada informe.

    Para que la cifra no se lea como "dinero disponible", se devuelve
    ``pendiente_de_cobro``: cuánto de lo vendido en el periodo sigue sin
    cobrarse.

    ## Productos y planes NO se suman

    La utilidad solo se puede calcular de los **productos**: su costo queda
    copiado en cada línea de venta (``detalle_ventas.costo_unitario``, el del
    catálogo en el momento de vender, no el de hoy).

    Un plan no tiene costo de adquisición: lo que cuesta prestarlo son el
    alquiler, el personal y los servicios, que viven en ``gastos`` (RF-24) y
    que HOY NO SE REGISTRAN DESDE NINGUNA PARTE -- los endpoints de gastos se
    implementaron y se retiraron por decisión de producto. Por eso los
    ingresos por planes se devuelven APARTE y sin utilidad asociada: sumarlos
    como si fueran ganancia daría una cifra alegre y falsa.

    Por lo mismo NO se devuelve ninguna "utilidad neta". Con la tabla de
    gastos siempre vacía, esa cifra sería el margen bruto de los productos
    con la etiqueta de "ganancia", que es precisamente lo que no debe
    enseñarse. El agregado de ``gastos`` sí se sigue devolviendo, en cero,
    para que la pantalla pueda decir que no están contemplados en vez de
    callarlo.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'costos.ver'

    def get(self, request):
        desde, hasta = _rango(request)
        zona = _zona_del_gimnasio(request)

        lineas = acotar_por_sede(
            request,
            DetalleVenta.objects.exclude(venta__estado=Venta.EstadoVenta.ANULADA),
            campo='venta__sede_id',
        )
        lineas = _filtrar_fechas(lineas, 'venta__fecha_hora', desde, hasta, zona)

        #: Costo de la línea. `total_linea` ya viene multiplicado por la
        #: cantidad (columna generada), pero `costo_unitario` no.
        costo_linea = F('costo_unitario') * F('cantidad')

        productos = lineas.filter(
            tipo_item=DetalleVenta.TipoItemVenta.PRODUCTO, producto__isnull=False,
        )
        resumen = productos.aggregate(
            ingresos=Coalesce(Sum('total_linea'), _CERO),
            costo=Coalesce(Sum(costo_linea), _CERO),
        )
        utilidad = resumen['ingresos'] - resumen['costo']

        detalle = [
            {
                'producto_id': fila['producto_id'],
                'producto_nombre': fila['producto__nombre'],
                'unidades': str(fila['unidades']),
                'ingresos': str(fila['ingresos']),
                'costo': str(fila['costo']),
                'utilidad': str(fila['ingresos'] - fila['costo']),
                'margen_pct': _porcentaje(fila['ingresos'] - fila['costo'], fila['ingresos']),
            }
            for fila in (
                productos.values('producto_id', 'producto__nombre')
                .annotate(
                    unidades=Coalesce(Sum('cantidad'), _CERO),
                    ingresos=Coalesce(Sum('total_linea'), _CERO),
                    costo=Coalesce(Sum(costo_linea), _CERO),
                )
                .order_by('-ingresos')
            )
        ]

        planes = lineas.filter(tipo_item=DetalleVenta.TipoItemVenta.PLAN).aggregate(
            ingresos=Coalesce(Sum('total_linea'), _CERO),
        )

        gastos = acotar_por_sede(request, Gasto.objects.all())
        if desde:
            gastos = gastos.filter(fecha__gte=desde)
        if hasta:
            gastos = gastos.filter(fecha__lte=hasta)
        gastos_agregado = gastos.aggregate(
            total=Coalesce(Sum('monto'), _CERO), numero=Count('id'),
        )

        # Cuánto de lo vendido EN ESTE PERIODO sigue sin cobrar. No se reparte
        # entre productos y planes: un pago parcial no se imputa a líneas
        # concretas, así que atribuirlo exigiría inventarse un prorrateo.
        saldos = acotar_por_sede(request, VistaVentaSaldo.objects.filter(saldo__gt=0))
        saldos = _filtrar_fechas(saldos, 'fecha_hora', desde, hasta, zona)
        pendiente = saldos.aggregate(total=Coalesce(Sum('saldo'), _CERO))['total']

        return Response({
            'productos': {
                'ingresos': str(resumen['ingresos']),
                'costo': str(resumen['costo']),
                'utilidad': str(utilidad),
                'margen_pct': _porcentaje(utilidad, resumen['ingresos']),
            },
            'planes': {'ingresos': str(planes['ingresos'])},
            'pendiente_de_cobro': str(pendiente),
            # Se devuelve aunque hoy sea siempre cero: así el frontend puede
            # decir "0 gastos registrados" en vez de callar que la utilidad
            # neta del gimnasio no está contemplada.
            'gastos': {
                'total': str(gastos_agregado['total']),
                'registrados': gastos_agregado['numero'],
            },
            'detalle': detalle,
        })


class ReporteCarteraView(APIView):
    """``GET /api/reportes/cartera/?sede`` (``reportes.ver``).

    Quién debe y cuánto, agrupado por cliente. Responde la pregunta que el
    resumen de ventas deja abierta: ese "2 ventas con abono parcial" no dice
    de quién son ni cuánto falta de cada una.

    NO acepta rango de fechas a propósito: una deuda no "pertenece" a un mes,
    sigue viva hasta que se cobre. Filtrarla por fecha daría un número menor
    que la deuda real y sería justo lo contrario de lo que hace falta para ir
    a cobrar.

    Se apoya en ``v_ventas_saldo``, que ya calcula el saldo por venta
    descontando pagos anulados y excluyendo ventas anuladas.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'reportes.ver'

    def get(self, request):

        qs = acotar_por_sede(request, VistaVentaSaldo.objects.filter(saldo__gt=0))
        filas = list(qs.order_by('fecha_hora'))

        # Nombres y consecutivos de una sola consulta cada uno: el listado
        # puede tener decenas de filas y no se va a pedir un cliente por fila.
        clientes = dict(
            Cliente.objects.filter(id__in=[f.cliente_id for f in filas if f.cliente_id])
            .values_list('id', 'nombre')
        )
        consecutivos = dict(
            Venta.objects.filter(id__in=[f.venta_id for f in filas])
            .values_list('id', 'consecutivo')
        )

        por_cliente = {}
        for fila in filas:
            # Una venta con saldo SIEMPRE tiene cliente (lo impone
            # `registrar_venta`), pero se contempla el hueco por si algún dato
            # antiguo lo tuviera vacío: mejor mostrarlo que ocultarlo.
            clave = fila.cliente_id
            entrada = por_cliente.setdefault(clave, {
                'cliente_id': clave,
                'cliente_nombre': clientes.get(clave, 'Sin cliente identificado'),
                'saldo_total': Decimal('0'),
                'ventas': [],
            })
            entrada['saldo_total'] += fila.saldo
            entrada['ventas'].append({
                'venta_id': fila.venta_id,
                'consecutivo': consecutivos.get(fila.venta_id),
                'fecha_hora': fila.fecha_hora,
                'total': str(fila.total),
                'total_pagado': str(fila.total_pagado),
                'saldo': str(fila.saldo),
            })

        deudores = sorted(por_cliente.values(), key=lambda d: d['saldo_total'], reverse=True)
        for deudor in deudores:
            deudor['saldo_total'] = str(deudor['saldo_total'])

        return Response({
            'deudores': deudores,
            'totales': {
                'saldo': str(sum((f.saldo for f in filas), start=Decimal('0'))),
                'clientes': len(deudores),
                'ventas': len(filas),
            },
        })


class ReporteProductosView(APIView):
    """``GET /api/reportes/productos/?desde&hasta&sede`` (``reportes.ver``).

    Qué se vendió de cada producto y cuánto queda.

    ``importe`` es BRUTO, antes del descuento de la venta:
    ``detalle_ventas.total_linea`` es ``cantidad * precio_unitario`` y el
    descuento vive en la cabecera de la venta, no en la línea. Repartirlo
    entre líneas exigiría inventarse un criterio de prorrateo, así que se
    devuelve el bruto y el descuento total aparte (en el informe de ventas).

    ``stock_actual`` es de la sede consultada, no del gimnasio entero: las
    existencias son por sede.
    """

    permission_classes = [TienePermiso]
    permiso_requerido = 'reportes.ver'

    def get(self, request):
        desde, hasta = _rango(request)
        zona = _zona_del_gimnasio(request)

        lineas = DetalleVenta.objects.filter(
            tipo_item=DetalleVenta.TipoItemVenta.PRODUCTO,
            producto__isnull=False,
        ).exclude(venta__estado=Venta.EstadoVenta.ANULADA)
        lineas = acotar_por_sede(request, lineas, campo='venta__sede_id')
        lineas = _filtrar_fechas(lineas, 'venta__fecha_hora', desde, hasta, zona)

        vendido = (
            lineas.values('producto_id', 'producto__nombre')
            .annotate(
                unidades=Coalesce(Sum('cantidad'), _CERO),
                importe=Coalesce(Sum('total_linea'), _CERO),
            )
            .order_by('-importe')
        )

        # Existencias actuales por producto. Es el saldo de HOY, no el del
        # final del rango: el kardex permitiría reconstruir el histórico, pero
        # lo que se quiere saber aquí es qué reponer ahora.
        stock_qs = acotar_por_sede(request, StockSede.objects.all())
        stock_por_producto = {
            fila['producto_id']: fila['cantidad']
            for fila in stock_qs.values('producto_id').annotate(cantidad=Coalesce(Sum('cantidad'), _CERO))
        }

        filas = [
            {
                'producto_id': fila['producto_id'],
                'producto_nombre': fila['producto__nombre'],
                'unidades': str(fila['unidades']),
                'importe': str(fila['importe']),
                'stock_actual': str(stock_por_producto.get(fila['producto_id'], 0)),
            }
            for fila in vendido
        ]

        total_unidades = sum((f['unidades'] for f in vendido), start=0)
        total_importe = sum((f['importe'] for f in vendido), start=0)

        return Response({
            'productos': filas,
            'totales': {
                'unidades': str(total_unidades),
                'importe': str(total_importe),
                'productos_distintos': len(filas),
            },
        })
