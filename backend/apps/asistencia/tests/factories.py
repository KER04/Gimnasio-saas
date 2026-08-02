"""Fábrica de datos para la batería de la API de asistencia (RF-15, sin
biometría).

``crear_escenario_asistencia`` siembra, para UN tenant: una sede, un cliente,
un plan mensual (30 días, para poder construir membresías vigentes/vencidas
a mano en cada test) y DOS usuarios asignados a la ÚNICA sede vía
``UsuarioSede`` (necesario: ``apps.asistencia.services._resolver_sede_usuario``
exige que el usuario esté asignado a exactamente una sede) --
``usuario_admin`` con ``asistencia.autorizar`` (además de
``clientes.ver``/``ventas.registrar``/``reportes.ver``) y
``usuario_sin_autorizar``, idéntico salvo por ESE permiso, para poder probar
el 403 de la Parte B9 sin tocar nada más.
"""
from decimal import Decimal

from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.membresias.models import Plan
from apps.organizacion.models import Permiso, Rol, RolPermiso, Sede, Usuario, UsuarioSede
from apps.plataforma.models import Tenant
from apps.ventas.models import Venta

PASSWORD = 'clave-super-segura-123'

PERMISOS_ADMIN = ('clientes.ver', 'ventas.registrar', 'reportes.ver', 'asistencia.autorizar')
PERMISOS_SIN_AUTORIZAR = ('clientes.ver', 'ventas.registrar', 'reportes.ver')


def crear_escenario_asistencia(subdominio, sufijo, using='default'):
    """:return: dict con ``tenant``, ``sede``, ``rol_admin``,
    ``rol_sin_autorizar``, ``usuario_admin`` (con ``asistencia.autorizar``,
    asignado a ``sede``), ``usuario_sin_autorizar`` (sin ese permiso,
    también asignado a ``sede``), ``cliente``, ``plan_mensual`` y ``venta``
    (una venta ya sembrada, sin pasar por ``apps.ventas.services``, para
    poder probar ``sesion_anonima``)."""
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

        rol_admin = Rol.objects.using(using).create(
            tenant=tenant, nombre=f'Administrador {sufijo}', es_sistema=True,
        )
        rol_sin_autorizar = Rol.objects.using(using).create(
            tenant=tenant, nombre=f'Recepcionista sin autorizar {sufijo}', es_sistema=True,
        )

        permisos_por_codigo = {p.codigo: p for p in Permiso.objects.using(using).all()}
        RolPermiso.objects.using(using).bulk_create([
            RolPermiso(rol=rol_admin, permiso=permisos_por_codigo[codigo], tenant=tenant)
            for codigo in PERMISOS_ADMIN
        ])
        RolPermiso.objects.using(using).bulk_create([
            RolPermiso(rol=rol_sin_autorizar, permiso=permisos_por_codigo[codigo], tenant=tenant)
            for codigo in PERMISOS_SIN_AUTORIZAR
        ])

        usuario_admin = Usuario.objects.db_manager(using).create_user(
            correo=f'admin.{subdominio}@example.com', nombre=f'Admin {sufijo}',
            tenant=tenant, rol=rol_admin, password=PASSWORD,
        )
        usuario_sin_autorizar = Usuario.objects.db_manager(using).create_user(
            correo=f'recepcion.{subdominio}@example.com', nombre=f'Recepción {sufijo}',
            tenant=tenant, rol=rol_sin_autorizar, password=PASSWORD,
        )
        UsuarioSede.objects.using(using).create(usuario=usuario_admin, sede=sede, tenant=tenant)
        UsuarioSede.objects.using(using).create(usuario=usuario_sin_autorizar, sede=sede, tenant=tenant)

        cliente = Cliente.objects.using(using).create(
            tenant=tenant, sede_origen=sede, nombre=f'Cliente {sufijo}',
            cedula=f'CED-{sufijo}-0001', telefono='3000000000', direccion='Calle 1 # 2-3',
        )

        plan_mensual = Plan.objects.using(using).create(
            tenant=tenant, nombre=f'Mensual {sufijo}', tipo=Plan.TipoPlan.MENSUAL,
            duracion_dias=30, precio=Decimal('80000.00'),
        )

        venta = Venta.objects.using(using).create(
            tenant=tenant, sede=sede, cliente=None, usuario=usuario_admin,
            consecutivo=1, subtotal=Decimal('15000.00'), total=Decimal('15000.00'),
            estado=Venta.EstadoVenta.PAGADA,
        )

    return {
        'tenant': tenant,
        'sede': sede,
        'rol_admin': rol_admin,
        'rol_sin_autorizar': rol_sin_autorizar,
        'usuario_admin': usuario_admin,
        'usuario_sin_autorizar': usuario_sin_autorizar,
        'cliente': cliente,
        'plan_mensual': plan_mensual,
        'venta': venta,
    }
