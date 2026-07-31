"""Fábrica de datos para la batería de la API de clientes (Parte C del
encargo, RF-03/RF-09/RF-16).

Sigue el mismo patrón que ``apps.ventas.tests.factories.crear_escenario_pos``:
un tenant con DOS roles (uno con ``clientes.ver`` + ``clientes.gestionar``,
otro solo con ``clientes.ver``, para poder probar el 403 de la Parte C9) y
DOS usuarios correspondientes. ``usuario_admin`` queda asignado a la ÚNICA
sede del tenant vía ``UsuarioSede``, para poder probar la resolución
automática de ``sede_origen`` cuando el POST no la indica explícitamente.

Además siembra una Venta+DetalleVenta+Pago contra el cliente inicial (sin
pasar por ``apps.ventas.services``, para no arrastrar todo el andamiaje de
inventario/planes que ese módulo necesita): basta con una fila real en
``ventas`` que referencie al cliente para poder comprobar, en la Parte C6,
que el borrado lógico del cliente no arrastra su histórico de compras.
"""
from decimal import Decimal

from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.inventario.models import CategoriaProducto, Producto
from apps.organizacion.models import Permiso, Rol, RolPermiso, SecuenciaComprobante, Sede, Usuario, UsuarioSede
from apps.plataforma.models import Tenant
from apps.ventas.models import CategoriaIngreso, DetalleVenta, Pago, Venta

PASSWORD = 'clave-super-segura-123'

PERMISOS_ADMIN = ('clientes.ver', 'clientes.gestionar')
PERMISOS_RECEPCIONISTA = ('clientes.ver',)


def crear_escenario_clientes(subdominio, sufijo, using='default'):
    """Crea un tenant listo para probar la API de clientes.

    :return: dict con ``tenant``, ``sede`` (única sede, asignada a
        ``usuario_admin`` vía ``UsuarioSede``), ``rol_admin``,
        ``rol_recepcion``, ``usuario_admin`` (``clientes.ver`` +
        ``clientes.gestionar``), ``usuario_recepcion`` (solo
        ``clientes.ver``), ``cliente`` (ya sembrado, con una venta
        histórica) y ``venta`` (la venta histórica de ese cliente).
    """
    tenant = Tenant.objects.using(using).create(
        nombre_comercial=f'Gimnasio {sufijo}',
        subdominio=subdominio,
        responsable=f'Responsable {sufijo}',
        correo=f'contacto.{subdominio}@example.com',
    )

    with tenant_context(tenant.id, using=using):
        sede = Sede.objects.using(using).create(
            tenant=tenant, nombre=f'Sede {sufijo}', direccion=f'Calle {sufijo} 1-11',
        )
        SecuenciaComprobante.objects.using(using).create(sede=sede, tenant=tenant)

        rol_admin = Rol.objects.using(using).create(
            tenant=tenant, nombre=f'Administrador {sufijo}', es_sistema=True,
        )
        rol_recepcion = Rol.objects.using(using).create(
            tenant=tenant, nombre=f'Recepcionista {sufijo}', es_sistema=True,
        )

        permisos_por_codigo = {p.codigo: p for p in Permiso.objects.using(using).all()}
        RolPermiso.objects.using(using).bulk_create([
            RolPermiso(rol=rol_admin, permiso=permisos_por_codigo[codigo], tenant=tenant)
            for codigo in PERMISOS_ADMIN
        ])
        RolPermiso.objects.using(using).bulk_create([
            RolPermiso(rol=rol_recepcion, permiso=permisos_por_codigo[codigo], tenant=tenant)
            for codigo in PERMISOS_RECEPCIONISTA
        ])

        usuario_admin = Usuario.objects.db_manager(using).create_user(
            correo=f'admin.{subdominio}@example.com', nombre=f'Admin {sufijo}',
            tenant=tenant, rol=rol_admin, password=PASSWORD,
        )
        usuario_recepcion = Usuario.objects.db_manager(using).create_user(
            correo=f'recepcion.{subdominio}@example.com', nombre=f'Recepción {sufijo}',
            tenant=tenant, rol=rol_recepcion, password=PASSWORD,
        )
        UsuarioSede.objects.using(using).create(usuario=usuario_admin, sede=sede, tenant=tenant)

        cliente = Cliente.objects.using(using).create(
            tenant=tenant, sede_origen=sede, nombre=f'Cliente {sufijo}',
            cedula=f'CED-{sufijo}-0001', telefono='3000000000', direccion='Calle 1 # 2-3',
        )

        categoria_producto = CategoriaProducto.objects.using(using).create(
            tenant=tenant, nombre=f'Suplementos {sufijo}',
        )
        producto = Producto.objects.using(using).create(
            tenant=tenant, categoria_producto=categoria_producto,
            nombre=f'Proteína {sufijo}', precio_venta=Decimal('60000.00'),
        )
        categoria_ingreso = CategoriaIngreso.objects.using(using).create(
            tenant=tenant, nombre=f'Ingresos {sufijo}',
        )

        venta = Venta.objects.using(using).create(
            tenant=tenant, sede=sede, cliente=cliente, usuario=usuario_admin,
            consecutivo=1, subtotal=producto.precio_venta, total=producto.precio_venta,
            estado=Venta.EstadoVenta.PARCIAL,
        )
        DetalleVenta.objects.using(using).create(
            tenant=tenant, venta=venta, tipo_item=DetalleVenta.TipoItemVenta.PRODUCTO,
            producto=producto, categoria_ingreso=categoria_ingreso,
            descripcion=producto.nombre, cantidad=Decimal('1'), precio_unitario=producto.precio_venta,
        )
        Pago.objects.using(using).create(
            tenant=tenant, venta=venta, usuario=usuario_admin,
            monto=Decimal('20000'), forma_pago=Pago.FormaPago.EFECTIVO, es_pago_inicial=True,
        )

    return {
        'tenant': tenant,
        'sede': sede,
        'rol_admin': rol_admin,
        'rol_recepcion': rol_recepcion,
        'usuario_admin': usuario_admin,
        'usuario_recepcion': usuario_recepcion,
        'cliente': cliente,
        'producto': producto,
        'venta': venta,
    }
