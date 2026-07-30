"""Fábrica de datos para la batería de aislamiento multi-tenant (Parte C).

``crear_tenant_completo`` siembra, para UN tenant, una fila en cada una de
las tablas pedidas por el documento de requisitos: Tenant, Sede, Rol,
Usuario, Cliente, Plan, Membresia, Producto (con CategoriaProducto), Venta
(con CategoriaIngreso + DetalleVenta + Pago).

## Por qué se siembra con ``tenant_context`` sobre 'default' y NO con 'ddl'

La consigna original (C1) pedía sembrar con la conexión ``ddl``
(superusuario ``postgres``, que se salta RLS igual con FORCE ROW LEVEL
SECURITY). Eso funciona perfectamente fuera de un test — por ejemplo en un
management command contra la base real. Pero DENTRO de un ``TestCase`` (o
``TransactionTestCase``) de Django deja de servir para lo que necesitamos
aquí:

- ``default`` y ``ddl`` apuntan a la MISMA base física, pero son DOS
  conexiones/roles distintos (keradmin y postgres respectivamente).
- Un INSERT hecho por la conexión ``ddl`` vive en la transacción de ESA
  conexión. Las pruebas leen los datos sembrados a través de la conexión
  ``default`` (la que de verdad está sometida a RLS, que es lo que
  queremos probar). Dos conexiones separadas no se ven las transacciones no
  confirmadas entre sí (aislamiento MVCC normal de PostgreSQL) y el test
  runner de Django JAMÁS hace commit real de los datos de una prueba (usa
  ROLLBACK o TRUNCATE para aislar pruebas entre sí) — así que un INSERT por
  'ddl' sencillamente no sería visible para una consulta por 'default'
  dentro del mismo test.

La solución (documentada también en el punto C4 del encargo) es sembrar
TODO —lectura y escritura— por la misma conexión 'default', usando
``tenant_context`` para satisfacer la política RLS
``WITH CHECK (tenant_id = fn_tenant_actual())`` en cada INSERT. Como
``tenant_context`` funciona igual de bien contra 'ddl' (allí es inocuo: un
superusuario ignora RLS), se deja el parámetro ``using`` configurable para
poder reutilizar esta misma función en un script real contra la base de
producción/desarrollo con ``using='ddl'`` si hiciera falta.
"""
import datetime
from decimal import Decimal

from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.inventario.models import CategoriaProducto, Producto
from apps.membresias.models import Membresia, Plan
from apps.organizacion.models import Rol, Sede, Usuario
from apps.plataforma.models import Tenant
from apps.ventas.models import CategoriaIngreso, DetalleVenta, Pago, Venta


def crear_tenant_completo(subdominio, sufijo, using='default'):
    """Crea un tenant con una fila en cada tabla clave del dominio.

    :param subdominio: subdominio del tenant (debe cumplir
        ``^[a-z0-9][a-z0-9-]{1,40}$``, es decir, minúsculas).
    :param sufijo: sufijo legible para nombrar las entidades creadas (p. ej.
        ``'A'``/``'B'``); también se usa para generar valores únicos
        (cédula, código de barras, etc.) entre tenants.
    :param using: alias de conexión Django. 'default' (por defecto) es
        obligatorio dentro de pruebas; 'ddl' es válido para sembrado fuera
        de pruebas, contra una base real, con el rol superusuario.
    :return: dict con las instancias creadas, indexadas por nombre de
        entidad (``tenant``, ``sede``, ``rol``, ``usuario``, ``cliente``,
        ``plan``, ``categoria_producto``, ``producto``,
        ``categoria_ingreso``, ``membresia``, ``venta``, ``detalle_venta``,
        ``pago``), para que los tests puedan comparar identidades (ids), no
        solo conteos.
    """
    # La tabla `tenants` NO lleva RLS (es del proveedor, no del gimnasio),
    # así que no hace falta ningún tenant_context para crearla.
    tenant = Tenant.objects.using(using).create(
        nombre_comercial=f'Gimnasio {sufijo}',
        subdominio=subdominio,
        responsable=f'Responsable {sufijo}',
        correo=f'contacto.{subdominio}@example.com',
    )

    with tenant_context(tenant.id, using=using):
        sede = Sede.objects.using(using).create(
            tenant=tenant,
            nombre=f'Sede {sufijo}',
            direccion=f'Calle {sufijo} # 1-23',
        )
        rol = Rol.objects.using(using).create(
            tenant=tenant,
            nombre=f'Administrador {sufijo}',
            es_sistema=True,
        )
        usuario = Usuario.objects.using(using).create(
            tenant=tenant,
            rol=rol,
            nombre=f'Usuario {sufijo}',
            correo=f'usuario.{subdominio}@example.com',
            password='hash-no-usado-en-pruebas',
        )
        cliente = Cliente.objects.using(using).create(
            tenant=tenant,
            sede_origen=sede,
            nombre=f'Cliente {sufijo}',
            cedula=f'CED-{sufijo}-0001',
            telefono='3000000000',
            direccion=f'Carrera {sufijo} # 4-56',
        )
        plan = Plan.objects.using(using).create(
            tenant=tenant,
            nombre=f'Plan mensual {sufijo}',
            tipo=Plan.TipoPlan.MENSUAL,
            duracion_dias=30,
            precio=Decimal('50000.00'),
        )
        categoria_producto = CategoriaProducto.objects.using(using).create(
            tenant=tenant,
            nombre=f'Suplementos {sufijo}',
        )
        producto = Producto.objects.using(using).create(
            tenant=tenant,
            categoria_producto=categoria_producto,
            nombre=f'Proteína {sufijo}',
            precio_venta=Decimal('20000.00'),
        )
        categoria_ingreso = CategoriaIngreso.objects.using(using).create(
            tenant=tenant,
            nombre=f'Ingresos varios {sufijo}',
        )

        hoy = datetime.date.today()
        membresia = Membresia.objects.using(using).create(
            tenant=tenant,
            cliente=cliente,
            plan=plan,
            sede=sede,
            vendedor=usuario,
            fecha_inicio=hoy,
            fecha_fin=hoy + datetime.timedelta(days=plan.duracion_dias),
            precio_pagado=plan.precio,
        )

        venta = Venta.objects.using(using).create(
            tenant=tenant,
            sede=sede,
            cliente=cliente,
            usuario=usuario,
            consecutivo=1,
            subtotal=producto.precio_venta,
            total=producto.precio_venta,
        )
        detalle_venta = DetalleVenta.objects.using(using).create(
            tenant=tenant,
            venta=venta,
            tipo_item=DetalleVenta.TipoItemVenta.PRODUCTO,
            producto=producto,
            categoria_ingreso=categoria_ingreso,
            descripcion=producto.nombre,
            cantidad=Decimal('1'),
            precio_unitario=producto.precio_venta,
        )
        pago = Pago.objects.using(using).create(
            tenant=tenant,
            venta=venta,
            usuario=usuario,
            monto=venta.total,
            forma_pago=Pago.FormaPago.EFECTIVO,
            es_pago_inicial=True,
        )

        # Enlaza la membresía con la venta que la originó, como en producción.
        membresia.venta = venta
        membresia.save(using=using)

    return {
        'tenant': tenant,
        'sede': sede,
        'rol': rol,
        'usuario': usuario,
        'cliente': cliente,
        'plan': plan,
        'categoria_producto': categoria_producto,
        'producto': producto,
        'categoria_ingreso': categoria_ingreso,
        'membresia': membresia,
        'venta': venta,
        'detalle_venta': detalle_venta,
        'pago': pago,
    }
