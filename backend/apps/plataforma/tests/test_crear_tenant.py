"""Pruebas del comando `crear_tenant` (Parte D).

## Por qué esta suite usa TransactionTestCase y NO TestCase

El comando escribe TODO por la conexión 'ddl' (superusuario, ver el
docstring de `crear_tenant.py`). Para comprobar que el tenant queda
REALMENTE utilizable hay que leer esos mismos datos por la conexión
'default' -- la que usa `TenantAuthBackend` en producción -- y dos conexiones
separadas no se ven las transacciones no confirmadas entre sí (el mismo
razonamiento, con más detalle, en
`apps/core/tests/test_aislamiento.py`). Con `TransactionTestCase` el
comando hace COMMIT real dentro de su propio `transaction.atomic(using='ddl')`
y esos datos sí quedan visibles para la conexión 'default' del resto de la
prueba.

Dos consecuencias de usar `TransactionTestCase`, no de `crear_tenant`:

- Las lecturas por 'default' contra tablas con RLS (`Rol`, `RolPermiso`) hay
  que envolverlas en ``tenant_context``: a diferencia de `TestCase`, aquí no
  hay ninguna transacción de petición HTTP que lo haga por nosotros.
- `TransactionTestCase` hace un FLUSH real (TRUNCATE) de las tablas después
  de CADA método de prueba, lo que borra también el catálogo `permisos`
  sembrado por RunSQL en la migración de `apps.core` (no es un fixture ni un
  `post_migrate`, así que Django no lo re-siembra solo). Se probó
  ``serialized_rollback = True`` (la solución "de libro" de Django para este
  caso) pero choca con OTRA `TransactionTestCase` de la suite
  (`apps.core.tests.test_aislamiento`, sin `serialized_rollback`): mezclar
  ambas en la misma corrida provoca un `IntegrityError` de clave duplicada al
  restaurar el snapshot serializado sobre una base que la otra clase no
  llegó a vaciar todavía (el orden entre clases `TransactionTestCase` no está
  garantizado). En vez de depender de ese orden, `setUp` resiembra el
  catálogo de permisos EXPLÍCITAMENTE si algún flush anterior lo dejó vacío
  -- funciona sin importar qué otra prueba corrió antes.
"""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from apps.autenticacion.backends import TenantAuthBackend
from apps.core.tenant import tenant_context
from apps.organizacion.models import Permiso, Rol, RolPermiso
from apps.plataforma.aprovisionamiento import TODOS_LOS_PERMISOS
from apps.plataforma.models import Tenant

PASSWORD = 'clave-de-prueba-123'


class CrearTenantCommandTestCase(TransactionTestCase):

    databases = {'default', 'ddl'}

    def setUp(self):
        # Re-siembra defensiva del catálogo global de permisos: otra
        # `TransactionTestCase` de la suite puede haber hecho FLUSH de la
        # base antes de que esta clase corra, y ese catálogo lo siembra
        # RunSQL (migración de apps.core), no un fixture ni un
        # `post_migrate` que Django reponga solo tras el flush.
        codigos_existentes = set(Permiso.objects.using('ddl').values_list('codigo', flat=True))
        faltantes = set(TODOS_LOS_PERMISOS) - codigos_existentes
        if faltantes:
            Permiso.objects.using('ddl').bulk_create([
                Permiso(codigo=codigo, modulo=codigo.split('.')[0], descripcion=codigo)
                for codigo in faltantes
            ])

    def test_crea_tenant_utilizable(self):
        """El tenant existe, tiene los 4 roles del sistema y el usuario
        administrador puede autenticarse de verdad (vía TenantAuthBackend,
        el mismo camino que usan /api/auth/login/ y el admin)."""
        call_command(
            'crear_tenant',
            nombre='Gimnasio de Prueba',
            subdominio='pruebacmd',
            correo='admin@pruebacmd.example.com',
            password=PASSWORD,
            sede='Sede Única',
        )

        tenant = Tenant.objects.using('default').get(subdominio='pruebacmd')
        self.assertEqual(tenant.nombre_comercial, 'Gimnasio de Prueba')

        # `Rol` tiene RLS con FORCE: sin fijar app.tenant_id en 'default' la
        # consulta vería 0 filas aunque existan (falla cerrado), no un error.
        with tenant_context(tenant.id, using='default'):
            roles = list(
                Rol.objects.using('default').filter(tenant=tenant).values_list('nombre', flat=True),
            )
            self.assertTrue(Rol.objects.using('default').filter(tenant=tenant, es_sistema=True).count() == 4)
        self.assertCountEqual(
            roles, ['administrador', 'administrador_sede', 'recepcionista', 'entrenador'],
        )

        backend = TenantAuthBackend()
        usuario = backend.authenticate(
            None, correo='admin@pruebacmd.example.com', password=PASSWORD, tenant_id=tenant.id,
        )
        self.assertIsNotNone(usuario, 'El usuario administrador sembrado por crear_tenant debe poder autenticarse.')
        # SIN acceso al admin de Django salvo que se pida a propósito: ese
        # panel enseña las tablas en crudo y se salta las validaciones de la
        # aplicación, así que no es una herramienta para el cliente. Antes se
        # concedía siempre.
        self.assertFalse(usuario.es_staff)
        self.assertFalse(usuario.es_superusuario)
        # `usuario.rol` es una FK: acceder a ella dispara una consulta NUEVA
        # (perezosa) contra `Rol`, fuera ya del tenant_context puntual que
        # abrió `authenticate()` -- hay que volver a fijarlo para esta lectura.
        with tenant_context(tenant.id, using='default'):
            self.assertEqual(usuario.rol.nombre, 'administrador')

    def test_con_admin_django_concede_el_acceso_tecnico(self):
        """La puerta al admin de Django sigue existiendo, pero hay que pedirla."""
        call_command(
            'crear_tenant',
            nombre='Gimnasio Con Admin',
            subdominio='pruebastaff',
            correo='admin@pruebastaff.example.com',
            password=PASSWORD,
            con_admin_django=True,
        )

        tenant = Tenant.objects.using('default').get(subdominio='pruebastaff')
        usuario = TenantAuthBackend().authenticate(
            None, correo='admin@pruebastaff.example.com', password=PASSWORD, tenant_id=tenant.id,
        )

        self.assertTrue(usuario.es_staff)
        self.assertTrue(usuario.es_superusuario)

    def test_recepcionista_no_tiene_permisos_de_costos(self):
        """Verificación explícita del encargo: el recepcionista NO lleva
        costos.ver ni gastos.gestionar (§2.1)."""
        call_command(
            'crear_tenant',
            nombre='Gimnasio de Prueba 2',
            subdominio='pruebacmd2',
            correo='admin@pruebacmd2.example.com',
            password=PASSWORD,
        )
        tenant = Tenant.objects.using('default').get(subdominio='pruebacmd2')
        with tenant_context(tenant.id, using='default'):
            rol_recepcion = Rol.objects.using('default').get(tenant=tenant, nombre='recepcionista')
            codigos = set(
                RolPermiso.objects.using('default')
                .filter(rol=rol_recepcion)
                .values_list('permiso__codigo', flat=True),
            )
        self.assertNotIn('costos.ver', codigos)
        self.assertNotIn('gastos.gestionar', codigos)
        self.assertIn('ventas.registrar', codigos)

    def test_subdominio_duplicado_falla_limpio(self):
        """Idempotencia negativa: reintentar con un subdominio ya usado
        falla con un CommandError claro, sin dejar datos a medias."""
        call_command(
            'crear_tenant', nombre='X', subdominio='dupe',
            correo='a@dupe.example.com', password=PASSWORD,
        )
        with self.assertRaises(CommandError):
            call_command(
                'crear_tenant', nombre='X2', subdominio='dupe',
                correo='b@dupe.example.com', password=PASSWORD,
            )
        # Un solo tenant con ese subdominio, no dos ni ninguno a medias.
        self.assertEqual(Tenant.objects.using('default').filter(subdominio='dupe').count(), 1)
