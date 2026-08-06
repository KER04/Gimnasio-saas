"""Crea (o actualiza) una cuenta del panel del proveedor.

Es la ÚNICA puerta de entrada inicial: ``usuarios_plataforma`` nace vacía y el
panel no tiene registro público -- a propósito, porque quien entra ahí ve
todos los gimnasios. Para dar de alta al primer administrador hace falta
acceso al servidor, que es justo la barrera que se quiere.

    python manage.py crear_usuario_plataforma \\
        --nombre "Kevin" --correo kevin@proveedor.com --password '...'

Con ``--password`` omitido la pide por consola sin mostrarla en pantalla, que
es lo preferible: un password en la línea de comandos queda en el historial
del shell.
"""
import getpass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.plataforma.models import UsuarioPlataforma


class Command(BaseCommand):
    help = 'Crea o actualiza una cuenta del panel del proveedor (usuarios_plataforma).'

    def add_arguments(self, parser):
        parser.add_argument('--nombre', required=True, help='Nombre de la persona.')
        parser.add_argument('--correo', required=True, help='Correo, único en todo el sistema.')
        parser.add_argument(
            '--password',
            help='Contraseña. Si se omite se pide por consola (recomendado).',
        )
        parser.add_argument(
            '--rol',
            default=UsuarioPlataforma.RolPlataforma.ADMINISTRADOR,
            choices=[rol for rol, _etiqueta in UsuarioPlataforma.RolPlataforma.choices],
            help='administrador (por defecto) o soporte.',
        )
        parser.add_argument(
            '--actualizar',
            action='store_true',
            help='Si el correo ya existe, cambia su contraseña y su rol en vez de fallar.',
        )

    def _pedir_password(self):
        password = getpass.getpass('Contraseña: ')
        if not password:
            raise CommandError('La contraseña no puede estar vacía.')
        if password != getpass.getpass('Repite la contraseña: '):
            raise CommandError('Las contraseñas no coinciden.')
        return password

    @transaction.atomic
    def handle(self, *args, **opciones):
        correo = opciones['correo'].strip()
        password = opciones['password'] or self._pedir_password()

        if len(password) < 12:
            # Más exigente que el mínimo de Django (8): esta cuenta gobierna
            # todos los gimnasios, no uno.
            raise CommandError('La contraseña debe tener al menos 12 caracteres.')

        existente = UsuarioPlataforma.objects.filter(correo__iexact=correo).first()

        if existente is not None and not opciones['actualizar']:
            raise CommandError(
                f'Ya existe una cuenta con el correo "{correo}". '
                'Usa --actualizar si quieres cambiarle la contraseña o el rol.',
            )

        usuario = existente or UsuarioPlataforma(correo=correo)
        usuario.nombre = opciones['nombre']
        usuario.rol = opciones['rol']
        usuario.activo = True
        usuario.set_password(password)
        usuario.save()

        verbo = 'actualizada' if existente is not None else 'creada'
        self.stdout.write(self.style.SUCCESS(
            f'Cuenta {verbo}: {usuario.correo} (rol {usuario.rol}, id={usuario.id})',
        ))
