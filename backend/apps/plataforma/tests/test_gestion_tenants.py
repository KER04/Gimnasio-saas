"""Fase 2 del panel: dar de alta, configurar y cambiar de estado un gimnasio.

Lo que más se comprueba aquí no es que los endpoints respondan, sino sus
CONSECUENCIAS: que el gimnasio nuevo nazca utilizable (su dueño puede entrar
de verdad), que suspender deje fuera a sus usuarios de inmediato y que
reactivar los deje volver sin esperar a que caduque ningún caché.
"""
import datetime

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.core.tenant import tenant_context
from apps.organizacion.models import Rol, RolPermiso, Sede, Usuario, UsuarioSede
from apps.plataforma.aprovisionamiento import PERMISOS_POR_ROL, ROLES_SISTEMA
from apps.plataforma.models import Tenant, UsuarioPlataforma

from .test_panel import PASSWORD_PANEL, _crear_cuenta_panel

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class BasePanelTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.admin = _crear_cuenta_panel('gestion.admin@proveedor.example.com')
        cls.soporte = _crear_cuenta_panel(
            'gestion.soporte@proveedor.example.com', UsuarioPlataforma.RolPlataforma.SOPORTE,
        )

    def setUp(self):
        # El caché guarda la resolución subdominio -> tenant (60 s, incluidos
        # los "no existe"). Entre pruebas hay que limpiarlo o una dejaría
        # sembrado el resultado de la anterior.
        cache.clear()

    def _cabecera(self, correo):
        respuesta = self.client.post(
            '/api/plataforma/login/',
            data={'correo': correo, 'password': PASSWORD_PANEL},
            content_type='application/json',
        )
        return {'HTTP_AUTHORIZATION': f'Bearer {respuesta.json()["access"]}'}

    def _como_admin(self):
        return self._cabecera('gestion.admin@proveedor.example.com')

    def _como_soporte(self):
        return self._cabecera('gestion.soporte@proveedor.example.com')


class AltaDeGimnasioTestCase(BasePanelTestCase):

    def _crear(self, **extra):
        cuerpo = {
            'nombre_comercial': 'Gimnasio Alta',
            'correo_admin': 'duenio@alta.example.com',
            **extra,
        }
        return self.client.post(
            '/api/plataforma/tenants/', data=cuerpo,
            content_type='application/json', **self._como_admin(),
        )

    def test_el_gimnasio_nace_utilizable(self):
        """Un alta a medias (sin roles, sin sede o sin usuario) sería peor que
        no tener alta: el cliente entra y no puede hacer nada."""
        respuesta = self._crear(subdominio='altauno')

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        tenant = Tenant.objects.get(subdominio='altauno')

        with tenant_context(tenant.id):
            self.assertEqual(Sede.objects.filter(tenant=tenant).count(), 1)
            self.assertCountEqual(
                Rol.objects.filter(tenant=tenant).values_list('nombre', flat=True),
                list(ROLES_SISTEMA),
            )
            self.assertEqual(
                RolPermiso.objects.filter(tenant=tenant).count(),
                sum(len(codigos) for codigos in PERMISOS_POR_ROL.values()),
            )
            usuario = Usuario.objects.get(tenant=tenant)
            self.assertEqual(usuario.correo, 'duenio@alta.example.com')
            self.assertTrue(UsuarioSede.objects.filter(usuario=usuario).exists())

    def test_el_duenio_puede_entrar_con_la_contrasena_devuelta(self):
        """La prueba que de verdad importa del alta: que la credencial que le
        vas a dar al cliente FUNCIONE. La contraseña se enseña una sola vez,
        así que si no sirviera no habría forma de recuperarla."""
        respuesta = self._crear(subdominio='altados')
        acceso = respuesta.json()['acceso_inicial']

        login = self.client.post(
            '/api/auth/login/',
            data={'correo': acceso['correo'], 'password': acceso['password']},
            content_type='application/json',
            HTTP_HOST='altados.testserver',
        )

        self.assertEqual(login.status_code, 200, login.content)

    def test_la_contrasena_se_genera_y_no_se_pide(self):
        respuesta = self._crear(subdominio='altatres', password='la-mia-123')
        acceso = respuesta.json()['acceso_inicial']

        self.assertGreaterEqual(len(acceso['password']), 16)
        self.assertNotEqual(acceso['password'], 'la-mia-123')

    def test_el_administrador_no_entra_al_admin_de_django(self):
        """Ese panel enseña las tablas en crudo y se salta las validaciones de
        la aplicación: no es una herramienta para el cliente."""
        self._crear(subdominio='altacuatro')
        tenant = Tenant.objects.get(subdominio='altacuatro')

        with tenant_context(tenant.id):
            usuario = Usuario.objects.get(tenant=tenant)

        self.assertFalse(usuario.es_staff)
        self.assertFalse(usuario.es_superusuario)

    def test_propone_el_subdominio_a_partir_del_nombre(self):
        respuesta = self._crear(nombre_comercial='Gimnasio del Norte')

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()['subdominio'], 'gimnasio-del-norte')

    def test_rechaza_un_subdominio_ocupado(self):
        self._crear(subdominio='altarepe')
        respuesta = self._crear(subdominio='altarepe', correo_admin='otro@alta.example.com')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('subdominio', respuesta.json())

    def test_rechaza_un_subdominio_invalido(self):
        respuesta = self._crear(subdominio='Con Espacios Y Mayúsculas')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('subdominio', respuesta.json())

    def test_soporte_no_puede_dar_de_alta(self):
        respuesta = self.client.post(
            '/api/plataforma/tenants/',
            data={'nombre_comercial': 'Gimnasio X', 'correo_admin': 'x@x.example.com'},
            content_type='application/json', **self._como_soporte(),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_un_alta_fallida_no_deja_nada_a_medias(self):
        """El aprovisionamiento va en una transacción: si revienta, no queda
        un tenant sin roles ni un subdominio quemado."""
        antes = Tenant.objects.count()
        respuesta = self._crear(subdominio='alta_invalido!!')

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Tenant.objects.count(), antes)


class ConfiguracionDeGimnasioTestCase(BasePanelTestCase):

    def setUp(self):
        super().setUp()
        respuesta = self.client.post(
            '/api/plataforma/tenants/',
            data={
                'nombre_comercial': 'Gimnasio Config',
                'subdominio': 'configuno',
                'correo_admin': 'duenio@config.example.com',
            },
            content_type='application/json', **self._como_admin(),
        )
        self.uuid = respuesta.json()['uuid_publico']

    def _editar(self, datos, cabecera=None):
        return self.client.patch(
            f'/api/plataforma/tenants/{self.uuid}/', data=datos,
            content_type='application/json', **(cabecera or self._como_admin()),
        )

    def test_edita_los_datos_de_contacto_y_la_configuracion(self):
        respuesta = self._editar({
            'ciudad': 'Bogotá', 'telefono': '3009998877', 'dias_aviso_vencimiento': 10,
        })

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(cuerpo['ciudad'], 'Bogotá')
        self.assertEqual(cuerpo['dias_aviso_vencimiento'], 10)

    def test_normaliza_la_moneda_a_mayusculas(self):
        self.assertEqual(self._editar({'moneda': 'usd'}).json()['moneda'], 'USD')

    def test_rechaza_una_zona_horaria_inventada(self):
        """No es un capricho de formato: `v_membresias_estado` y
        `v_corte_diario` calculan con ella qué día es en el gimnasio."""
        respuesta = self._editar({'zona_horaria': 'Marte/Olympus'})

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('zona_horaria', respuesta.json())

    def test_rechaza_valores_fuera_de_rango_con_400_y_no_con_500(self):
        """La base ya lo impide con un CHECK, pero un CHECK violado sale como
        IntegrityError -> 500. Validarlo aquí lo convierte en algo legible."""
        for campo, valor in (('dias_aviso_vencimiento', 999), ('minutos_antipassback', 99999)):
            with self.subTest(campo=campo):
                respuesta = self._editar({campo: valor})
                self.assertEqual(respuesta.status_code, 400, respuesta.content)
                self.assertIn(campo, respuesta.json())

    def test_el_subdominio_no_se_puede_cambiar(self):
        """Es la URL del cliente: cambiarla rompe sus enlaces y expulsa a
        quien tenga la sesión abierta. El campo se ignora en silencio porque
        no forma parte del serializer de edición."""
        respuesta = self._editar({'subdominio': 'otracosa'})

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['subdominio'], 'configuno')
        self.assertTrue(Tenant.objects.filter(subdominio='configuno').exists())

    def test_el_estado_no_se_cambia_editando(self):
        """Tiene su propia acción, con confirmación: suspender no puede
        ocurrir de refilón mientras se corrige un teléfono."""
        respuesta = self._editar({'estado': 'suspendido'})

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertEqual(respuesta.json()['estado'], 'prueba')

    def test_soporte_no_puede_editar(self):
        respuesta = self._editar({'ciudad': 'Cali'}, self._como_soporte())

        self.assertEqual(respuesta.status_code, 403, respuesta.content)

    def test_soporte_si_puede_consultar(self):
        respuesta = self.client.get(
            f'/api/plataforma/tenants/{self.uuid}/', **self._como_soporte(),
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)


class CambioDeEstadoTestCase(BasePanelTestCase):

    def setUp(self):
        super().setUp()
        respuesta = self.client.post(
            '/api/plataforma/tenants/',
            data={
                'nombre_comercial': 'Gimnasio Estado',
                'subdominio': 'estadouno',
                'correo_admin': 'duenio@estado.example.com',
            },
            content_type='application/json', **self._como_admin(),
        )
        self.uuid = respuesta.json()['uuid_publico']
        self.acceso = respuesta.json()['acceso_inicial']

    def _cambiar(self, estado, confirmacion='estadouno', cabecera=None):
        return self.client.post(
            f'/api/plataforma/tenants/{self.uuid}/estado/',
            data={'estado': estado, 'confirmacion': confirmacion},
            content_type='application/json', **(cabecera or self._como_admin()),
        )

    def _login_del_duenio(self):
        return self.client.post(
            '/api/auth/login/',
            data={'correo': self.acceso['correo'], 'password': self.acceso['password']},
            content_type='application/json',
            HTTP_HOST='estadouno.testserver',
        )

    def test_exige_escribir_el_subdominio_para_confirmar(self):
        """La lista del panel es una tabla de filas parecidas y el botón
        expulsa a todo un gimnasio: equivocarse de fila es demasiado fácil."""
        respuesta = self._cambiar('suspendido', confirmacion='otra-cosa')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('confirmacion', respuesta.json())
        self.assertEqual(Tenant.objects.get(subdominio='estadouno').estado, 'prueba')

    def test_suspender_deja_fuera_al_gimnasio_de_inmediato(self):
        """LA PRUEBA QUE IMPORTA de esta acción.

        El middleware cachea la resolución del subdominio 60 segundos. Sin
        invalidar ese caché, el gimnasio seguiría operando durante un minuto
        justo después de que alguien decidiera suspenderlo.
        """
        self.assertEqual(self._login_del_duenio().status_code, 200)

        self.assertEqual(self._cambiar('suspendido').status_code, 200)

        self.assertNotEqual(self._login_del_duenio().status_code, 200)

    def test_reactivar_deja_entrar_sin_esperar_al_cache(self):
        """El caché guarda también los "no existe": sin invalidarlo, un
        gimnasio recién reactivado seguiría rebotando a sus usuarios."""
        self._cambiar('suspendido')
        self.assertNotEqual(self._login_del_duenio().status_code, 200)

        self.assertEqual(self._cambiar('activo').status_code, 200)

        self.assertEqual(self._login_del_duenio().status_code, 200)

    def test_cancelar_programa_la_purga(self):
        respuesta = self._cambiar('cancelado')

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        hoy = datetime.date.today()
        self.assertEqual(cuerpo['fecha_cancelacion'], hoy.isoformat())
        # RF-21: retención 30+60 días.
        self.assertEqual(
            cuerpo['fecha_purga_datos'], (hoy + datetime.timedelta(days=91)).isoformat(),
        )

    def test_reactivar_borra_la_purga_programada(self):
        """Si no se limpiara, el gimnasio quedaría activo pero con una purga
        pendiente, y un proceso posterior borraría los datos de un cliente que
        está operando."""
        self._cambiar('cancelado')

        cuerpo = self._cambiar('activo').json()

        self.assertIsNone(cuerpo['fecha_cancelacion'])
        self.assertIsNone(cuerpo['fecha_purga_datos'])

    def test_rechaza_cambiar_al_estado_que_ya_tiene(self):
        respuesta = self._cambiar('prueba')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('estado', respuesta.json())

    def test_rechaza_un_estado_inexistente(self):
        self.assertEqual(self._cambiar('inventado').status_code, 400)

    def test_soporte_no_puede_cambiar_el_estado(self):
        respuesta = self._cambiar('suspendido', cabecera=self._como_soporte())

        self.assertEqual(respuesta.status_code, 403, respuesta.content)
        self.assertEqual(Tenant.objects.get(subdominio='estadouno').estado, 'prueba')

    def test_no_existe_borrado_de_gimnasios(self):
        """El ciclo de vida termina en `cancelado`. Un botón de borrar en un
        panel web es una forma muy fácil de destruir un cliente entero."""
        respuesta = self.client.delete(
            f'/api/plataforma/tenants/{self.uuid}/', **self._como_admin(),
        )

        self.assertEqual(respuesta.status_code, 405, respuesta.content)
        self.assertTrue(Tenant.objects.filter(subdominio='estadouno').exists())
