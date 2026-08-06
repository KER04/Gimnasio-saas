"""Comando de arranque de un tenant nuevo (Parte D).

    python manage.py crear_tenant --nombre "Gimnasio X" --subdominio gimx \
        --correo admin@gimx.com --password <clave> --sede "Sede Principal"

El alta en sí (tenant, sede, roles, permisos, semillas y usuario
administrador) vive en ``apps.plataforma.aprovisionamiento``: la MISMA
operación se puede lanzar desde aquí o desde el panel del proveedor, y tener
dos copias garantizaría que tarde o temprano una sembrara algo que la otra
no. Este módulo solo se ocupa de lo que es propio de la consola: leer
argumentos, resolver el subdominio y contar qué se creó.

## Por qué siembra por la conexión 'ddl'

Este comando corre fuera de cualquier petición HTTP: no hay
``TenantMiddleware`` que abra una transacción con ``app.tenant_id`` fijado.
'ddl' es la conexión de superusuario (``postgres``) reservada para DDL y
sembrado (ver settings/base.py); un superusuario de PostgreSQL ignora RLS
incluso con FORCE ROW LEVEL SECURITY. El panel, en cambio, siembra por la
conexión normal fijando el contexto del tenant nuevo -- ver el docstring de
``aprovisionamiento``.

## Idempotencia

No es idempotente en el sentido de "se puede correr dos veces con los
mismos argumentos y no pasa nada": el segundo intento con el mismo
``--subdominio`` falla limpio (``CommandError``) porque el subdominio ya
existe -- nunca deja una fila a medias ni un tenant duplicado.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.utils import DataError

from apps.plataforma.aprovisionamiento import (
    CATEGORIAS_GASTO,
    CATEGORIAS_INGRESO,
    CATEGORIAS_PRODUCTO,
    GRUPOS_MUSCULARES,
    PERMISOS_POR_ROL,
    ROLES_SISTEMA,
    AprovisionamientoError,
    aprovisionar_tenant,
)
from apps.plataforma.models import Tenant
from apps.plataforma.subdominios import (
    SubdominioInvalido,
    buscar_disponible,
    proponer_subdominio,
    validar_subdominio,
)


class Command(BaseCommand):
    help = (
        'Crea un tenant nuevo, listo para usar: sede, roles del sistema con '
        'sus permisos, semillas base (RF-17) y el usuario administrador.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--nombre', required=True, help='Nombre comercial del gimnasio.')
        parser.add_argument(
            '--subdominio',
            help=(
                'Subdominio único. Si se omite, se propone a partir del nombre. '
                'Conviene indicarlo a mano cuando la propuesta quede larga o '
                'poco comercial: es la URL que verá el cliente.'
            ),
        )
        parser.add_argument('--correo', required=True, help='Correo del usuario administrador.')
        parser.add_argument('--password', required=True, help='Contraseña del usuario administrador.')
        parser.add_argument(
            '--sede', default='Sede Principal',
            help='Nombre de la primera sede (por defecto "Sede Principal").',
        )
        parser.add_argument(
            '--con-admin-django',
            action='store_true',
            help=(
                'Concede al administrador acceso al panel técnico de Django '
                '(es_staff). Por defecto NO: ese panel enseña las tablas en '
                'crudo y se salta las validaciones de la aplicación.'
            ),
        )

    @staticmethod
    def _esta_ocupado(subdominio):
        return Tenant.objects.using('ddl').filter(subdominio__iexact=subdominio).exists()

    def _resolver_subdominio(self, nombre, subdominio_pedido):
        """Decide el subdominio final y lo valida.

        Si el operador lo indicó a mano y ya está ocupado, falla en vez de
        buscarle una variante: le daría una URL que no pidió y de la que no
        se enteraría hasta que el cliente se quejara. Cuando se propone
        automáticamente sí se busca la siguiente libre, porque ahí no hay
        ninguna expectativa que romper.
        """
        if subdominio_pedido:
            subdominio = subdominio_pedido.strip().lower()
            try:
                validar_subdominio(subdominio)
            except SubdominioInvalido as exc:
                raise CommandError(str(exc)) from exc
            if self._esta_ocupado(subdominio):
                raise CommandError(
                    f'Ya existe un gimnasio con el subdominio "{subdominio}". '
                    'Elige otro o borra el existente antes de reintentar.'
                )
            return subdominio

        try:
            propuesta = proponer_subdominio(nombre)
            validar_subdominio(propuesta)
            subdominio = buscar_disponible(propuesta, self._esta_ocupado)
        except SubdominioInvalido as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f'Subdominio propuesto a partir del nombre: "{subdominio}"')
        return subdominio

    def handle(self, *args, **options):
        nombre = options['nombre'].strip()
        correo = options['correo'].strip().lower()
        nombre_sede = options['sede'].strip()
        subdominio = self._resolver_subdominio(nombre, options.get('subdominio'))

        try:
            with transaction.atomic(using='ddl'):
                tenant, sede, usuario_admin = aprovisionar_tenant(
                    nombre=nombre,
                    subdominio=subdominio,
                    correo_admin=correo,
                    password_admin=options['password'],
                    nombre_sede=nombre_sede,
                    conexion='ddl',
                    con_admin_django=options['con_admin_django'],
                )
        except AprovisionamientoError as exc:
            raise CommandError(str(exc)) from exc
        except (IntegrityError, DataError) as exc:
            raise CommandError(f'No se pudo crear el tenant: {exc}') from exc

        total_asignaciones = sum(len(codigos) for codigos in PERMISOS_POR_ROL.values())

        self.stdout.write(self.style.SUCCESS(
            f'Tenant "{nombre}" creado correctamente (id={tenant.id}, subdominio="{subdominio}").'
        ))
        self.stdout.write(f'  Sede:               {sede.nombre} (id={sede.id})')
        self.stdout.write(f'  Roles del sistema:  {", ".join(ROLES_SISTEMA)}')
        self.stdout.write(f'  Permisos asignados: {total_asignaciones}')
        self.stdout.write(
            f'  Semillas:           {len(CATEGORIAS_PRODUCTO)} categorías de producto, '
            f'{len(CATEGORIAS_INGRESO)} categorías de ingreso, '
            f'{len(CATEGORIAS_GASTO)} categorías de gasto, '
            f'{len(GRUPOS_MUSCULARES)} grupos musculares.'
        )
        self.stdout.write(
            f'  Usuario admin:      {usuario_admin.correo} (rol administrador, '
            f'es_staff={usuario_admin.es_staff})'
        )
        if usuario_admin.es_staff:
            self.stdout.write(self.style.SUCCESS(
                f'  Admin de Django:    http://{subdominio}.localhost:8000/admin/'
            ))
