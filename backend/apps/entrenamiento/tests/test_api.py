"""Entrenamiento (RF-12): catálogo de ejercicios, rutinas y medidas.

El módulo tiene tres invariantes que la base impone y que la API tiene que
traducir a errores legibles en vez de a un 500: nombres de ejercicio únicos,
una sola ficha de medidas abierta por cliente, y numeración correlativa de
los controles.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.autenticacion.tests.test_auth import _cabecera_token, _crear_tenant_con_usuario
from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.entrenamiento.models import Ejercicio, FichaMedidas, GrupoMuscular, Rutina, RutinaDia
from apps.organizacion.models import Sede

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class BaseEntrenamientoTestCase(TestCase):
    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cache.clear()
        cls.tenant, cls.rol, cls.usuario = _crear_tenant_con_usuario(
            'entrena', 'EN', 'entrenador@entrena.example.com',
            permisos=('rutinas.gestionar', 'medidas.gestionar'),
        )
        with tenant_context(cls.tenant.id):
            cls.sede = Sede.objects.create(
                tenant=cls.tenant, nombre='Sede Única', direccion='Calle 1',
            )
            cls.cliente = Cliente.objects.create(
                tenant=cls.tenant, sede_origen=cls.sede, nombre='Cliente Prueba',
                cedula='9001', telefono='300', direccion='Calle 2',
            )
            cls.grupo = GrupoMuscular.objects.create(
                tenant=cls.tenant, nombre='Pecho', orden=1,
            )
            cls.grupo_pierna = GrupoMuscular.objects.create(
                tenant=cls.tenant, nombre='Pierna', orden=2,
            )

    def setUp(self):
        cache.clear()

    def _peticion(self, metodo, url, datos=None, usuario=None):
        fn = getattr(self.client, metodo)
        kwargs = {
            'HTTP_HOST': 'entrena.testserver',
            **_cabecera_token(usuario or self.usuario),
        }
        if datos is not None:
            kwargs['data'] = datos
            kwargs['content_type'] = 'application/json'
        return fn(url, **kwargs)

    def _crear_ejercicio(self, nombre='Press banca', grupo=None):
        return self._peticion('post', '/api/ejercicios/', {
            'nombre': nombre, 'grupo_muscular': (grupo or self.grupo).id,
        })


class CatalogoDeEjerciciosTestCase(BaseEntrenamientoTestCase):

    def test_crea_un_ejercicio(self):
        respuesta = self._crear_ejercicio()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()['grupo_nombre'], 'Pecho')

    def test_el_nombre_es_unico_sin_importar_mayusculas(self):
        self._crear_ejercicio()

        respuesta = self._crear_ejercicio(nombre='press BANCA')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('nombre', respuesta.json())

    def test_la_baja_es_logica_y_reversible(self):
        """`RutinaEjercicio.ejercicio` es PROTECT: borrar un ejercicio usado
        dejaría rutinas antiguas sin poder explicarse."""
        ejercicio_id = self._crear_ejercicio().json()['id']

        self._peticion('delete', f'/api/ejercicios/{ejercicio_id}/')

        visibles = self._peticion('get', '/api/ejercicios/').json()['results']
        self.assertNotIn(ejercicio_id, [e['id'] for e in visibles])

        todos = self._peticion('get', '/api/ejercicios/?incluir_inactivos=1').json()['results']
        self.assertIn(ejercicio_id, [e['id'] for e in todos])

        self._peticion('patch', f'/api/ejercicios/{ejercicio_id}/', {'activo': True})
        with tenant_context(self.tenant.id):
            self.assertTrue(Ejercicio.objects.get(pk=ejercicio_id).activo)

    def test_filtra_por_grupo_muscular(self):
        self._crear_ejercicio('Press banca', self.grupo)
        self._crear_ejercicio('Sentadilla', self.grupo_pierna)

        respuesta = self._peticion('get', f'/api/ejercicios/?grupo={self.grupo_pierna.id}')

        nombres = [e['nombre'] for e in respuesta.json()['results']]
        self.assertEqual(nombres, ['Sentadilla'])

    def test_sin_permiso_no_se_toca_el_catalogo(self):
        _t, _r, sin_permiso = _crear_tenant_con_usuario(
            'entrenasinperm', 'ESP', 'nadie@entrenasinperm.example.com',
        )

        respuesta = self.client.get(
            '/api/ejercicios/', HTTP_HOST='entrenasinperm.testserver',
            **_cabecera_token(sin_permiso),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)


class RutinasTestCase(BaseEntrenamientoTestCase):

    def _crear_rutina(self, **extra):
        ejercicio = self._crear_ejercicio().json()['id']
        cuerpo = {
            'cliente': self.cliente.id,
            'nombre': 'Fuerza 3 días',
            'dias': [
                {'numero': 1, 'nombre': 'Empuje', 'ejercicios': [
                    {'ejercicio': ejercicio, 'orden': 1, 'series': 4,
                     'repeticiones': 8, 'peso_kg': '60'},
                ]},
                {'numero': 2, 'nombre': 'Pierna', 'ejercicios': []},
            ],
            **extra,
        }
        return self._peticion('post', '/api/rutinas/', cuerpo), ejercicio

    def test_guarda_la_rutina_entera_de_una_vez(self):
        """Es un documento, no filas sueltas: el entrenador la arma de una vez
        y la guarda de una vez."""
        respuesta, _ejercicio = self._crear_rutina()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual(len(cuerpo['dias']), 2)
        self.assertEqual(len(cuerpo['dias'][0]['ejercicios']), 1)
        self.assertEqual(cuerpo['dias'][0]['ejercicios'][0]['ejercicio_nombre'], 'Press banca')

    def test_el_entrenador_es_quien_la_crea_y_no_un_id_del_cuerpo(self):
        """Si viniera de fuera se podrían atribuir rutinas a otra persona."""
        respuesta, _ejercicio = self._crear_rutina(entrenador=99999)

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        with tenant_context(self.tenant.id):
            self.assertEqual(
                Rutina.objects.get(pk=respuesta.json()['id']).entrenador_id, self.usuario.id,
            )

    def test_rechaza_dos_dias_con_el_mismo_numero(self):
        respuesta = self._peticion('post', '/api/rutinas/', {
            'cliente': self.cliente.id, 'nombre': 'Repetida',
            'dias': [{'numero': 1, 'nombre': 'A'}, {'numero': 1, 'nombre': 'B'}],
        })

        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_rechaza_dos_ejercicios_en_la_misma_posicion(self):
        ejercicio = self._crear_ejercicio().json()['id']

        respuesta = self._peticion('post', '/api/rutinas/', {
            'cliente': self.cliente.id, 'nombre': 'Orden repetido',
            'dias': [{'numero': 1, 'nombre': 'A', 'ejercicios': [
                {'ejercicio': ejercicio, 'orden': 1, 'series': 3, 'repeticiones': 10},
                {'ejercicio': ejercicio, 'orden': 1, 'series': 3, 'repeticiones': 10},
            ]}],
        })

        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_rechaza_series_o_repeticiones_en_cero(self):
        ejercicio = self._crear_ejercicio().json()['id']

        for campo in ('series', 'repeticiones'):
            with self.subTest(campo=campo):
                valores = {'series': 3, 'repeticiones': 10, campo: 0}
                respuesta = self._peticion('post', '/api/rutinas/', {
                    'cliente': self.cliente.id, 'nombre': f'Mala {campo}',
                    'dias': [{'numero': 1, 'nombre': 'A', 'ejercicios': [
                        {'ejercicio': ejercicio, 'orden': 1, **valores},
                    ]}],
                })
                self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_no_se_puede_usar_un_ejercicio_dado_de_baja(self):
        ejercicio = self._crear_ejercicio().json()['id']
        self._peticion('delete', f'/api/ejercicios/{ejercicio}/')

        respuesta = self._peticion('post', '/api/rutinas/', {
            'cliente': self.cliente.id, 'nombre': 'Con ejercicio retirado',
            'dias': [{'numero': 1, 'nombre': 'A', 'ejercicios': [
                {'ejercicio': ejercicio, 'orden': 1, 'series': 3, 'repeticiones': 10},
            ]}],
        })

        self.assertEqual(respuesta.status_code, 400, respuesta.content)

    def test_editar_los_dias_los_sustituye(self):
        respuesta, ejercicio = self._crear_rutina()
        rutina_id = respuesta.json()['id']

        actualizada = self._peticion('patch', f'/api/rutinas/{rutina_id}/', {
            'dias': [{'numero': 1, 'nombre': 'Todo junto', 'ejercicios': [
                {'ejercicio': ejercicio, 'orden': 1, 'series': 3, 'repeticiones': 10},
            ]}],
        })

        self.assertEqual(actualizada.status_code, 200, actualizada.content)
        self.assertEqual(len(actualizada.json()['dias']), 1)
        with tenant_context(self.tenant.id):
            self.assertEqual(RutinaDia.objects.filter(rutina_id=rutina_id).count(), 1)

    def test_editar_sin_mandar_dias_los_deja_intactos(self):
        """Cambiar el objetivo no debe borrar la rutina entera."""
        respuesta, _ejercicio = self._crear_rutina()
        rutina_id = respuesta.json()['id']

        actualizada = self._peticion(
            'patch', f'/api/rutinas/{rutina_id}/', {'objetivo': 'Ganar fuerza'},
        )

        self.assertEqual(len(actualizada.json()['dias']), 2)

    def test_rechaza_una_rutina_que_termina_antes_de_empezar(self):
        respuesta = self._peticion('post', '/api/rutinas/', {
            'cliente': self.cliente.id, 'nombre': 'Imposible',
            'fecha_inicio': '2026-06-01', 'fecha_fin': '2026-05-01',
        })

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('fecha_fin', respuesta.json())

    def test_archivar_no_borra_el_historico(self):
        respuesta, _ejercicio = self._crear_rutina()
        rutina_id = respuesta.json()['id']

        self._peticion('delete', f'/api/rutinas/{rutina_id}/')

        with tenant_context(self.tenant.id):
            self.assertFalse(Rutina.objects.get(pk=rutina_id).activa)
        archivadas = self._peticion('get', '/api/rutinas/?incluir_inactivas=1').json()['results']
        self.assertIn(rutina_id, [r['id'] for r in archivadas])


class MedidasTestCase(BaseEntrenamientoTestCase):

    def _abrir_ficha(self, **extra):
        return self._peticion('post', '/api/fichas-medidas/', {
            'cliente': self.cliente.id, 'estatura_cm': '175', **extra,
        })

    def test_abre_una_ficha(self):
        respuesta = self._abrir_ficha()

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(respuesta.json()['cliente_nombre'], 'Cliente Prueba')

    def test_solo_una_ficha_abierta_por_cliente(self):
        """`uq_ficha_cliente_activa` lo impone. Sin este 400 sería un 500."""
        self._abrir_ficha()

        respuesta = self._abrir_ficha()

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('cliente', respuesta.json())

    def test_la_estatura_va_en_centimetros(self):
        """El error más frecuente del formulario: escribir 1,75 donde van 175."""
        respuesta = self._abrir_ficha(estatura_cm='1.75')

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('estatura_cm', respuesta.json())

    def test_cerrar_permite_empezar_un_proceso_nuevo(self):
        ficha_id = self._abrir_ficha().json()['id']

        self._peticion('post', f'/api/fichas-medidas/{ficha_id}/cerrar/', {})
        segunda = self._abrir_ficha()

        self.assertEqual(segunda.status_code, 201, segunda.content)
        with tenant_context(self.tenant.id):
            self.assertEqual(FichaMedidas.objects.filter(cliente=self.cliente).count(), 2)

    def test_los_controles_se_numeran_solos_y_en_orden(self):
        """El número lo pone el servidor: dejarlo al cliente HTTP invitaría a
        repetirlo y chocar con `uq_control_numero`."""
        ficha_id = self._abrir_ficha().json()['id']

        numeros = [
            self._peticion(
                'post', f'/api/fichas-medidas/{ficha_id}/controles/', {'peso_kg': peso},
            ).json()['numero_control']
            for peso in ('80', '78', '76')
        ]

        self.assertEqual(numeros, [1, 2, 3])

    def test_las_medidas_son_opcionales(self):
        """En la práctica no siempre se toman las 13, y exigirlas haría que no
        se registrara ninguna."""
        ficha_id = self._abrir_ficha().json()['id']

        respuesta = self._peticion(
            'post', f'/api/fichas-medidas/{ficha_id}/controles/', {'peso_kg': '80'},
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertIsNone(respuesta.json()['cuello'])

    def test_rechaza_una_medida_no_positiva(self):
        ficha_id = self._abrir_ficha().json()['id']

        respuesta = self._peticion(
            'post', f'/api/fichas-medidas/{ficha_id}/controles/', {'abdomen': '0'},
        )

        self.assertEqual(respuesta.status_code, 400, respuesta.content)
        self.assertIn('abdomen', respuesta.json())

    def test_la_comparativa_calcula_la_diferencia(self):
        """Es la vista para la que existe la tabla: ¿bajó el abdomen?"""
        ficha_id = self._abrir_ficha().json()['id']
        for abdomen in ('95', '92', '89'):
            self._peticion(
                'post', f'/api/fichas-medidas/{ficha_id}/controles/', {'abdomen': abdomen},
            )

        respuesta = self._peticion('get', f'/api/fichas-medidas/{ficha_id}/comparativa/')

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        cuerpo = respuesta.json()
        self.assertEqual([c['numero_control'] for c in cuerpo['controles']], [1, 2, 3])
        abdomen = next(f for f in cuerpo['filas'] if f['medida'] == 'abdomen')
        self.assertEqual(abdomen['valores'], ['95.00', '92.00', '89.00'])
        self.assertEqual(float(abdomen['diferencia']), -6.0)

    def test_la_diferencia_ignora_los_controles_donde_no_se_tomo_la_medida(self):
        """Si en el control del medio no se midió el cuello, la diferencia
        debe seguir calculándose entre las veces que sí se midió."""
        ficha_id = self._abrir_ficha().json()['id']
        self._peticion('post', f'/api/fichas-medidas/{ficha_id}/controles/', {'cuello': '40'})
        self._peticion('post', f'/api/fichas-medidas/{ficha_id}/controles/', {'peso_kg': '80'})
        self._peticion('post', f'/api/fichas-medidas/{ficha_id}/controles/', {'cuello': '38'})

        cuerpo = self._peticion(
            'get', f'/api/fichas-medidas/{ficha_id}/comparativa/',
        ).json()

        cuello = next(f for f in cuerpo['filas'] if f['medida'] == 'cuello')
        self.assertEqual(cuello['valores'], ['40.00', None, '38.00'])
        self.assertEqual(float(cuello['diferencia']), -2.0)

    def test_una_sola_medicion_no_tiene_diferencia(self):
        ficha_id = self._abrir_ficha().json()['id']
        self._peticion('post', f'/api/fichas-medidas/{ficha_id}/controles/', {'abdomen': '95'})

        cuerpo = self._peticion(
            'get', f'/api/fichas-medidas/{ficha_id}/comparativa/',
        ).json()

        abdomen = next(f for f in cuerpo['filas'] if f['medida'] == 'abdomen')
        self.assertIsNone(abdomen['diferencia'])

    def test_sin_permiso_de_medidas_no_se_ven_las_fichas(self):
        _t, _r, solo_rutinas = _crear_tenant_con_usuario(
            'entrenasolorut', 'ESR', 'solo@entrenasolorut.example.com',
            permisos=('rutinas.gestionar',),
        )

        respuesta = self.client.get(
            '/api/fichas-medidas/', HTTP_HOST='entrenasolorut.testserver',
            **_cabecera_token(solo_rutinas),
        )

        self.assertEqual(respuesta.status_code, 403, respuesta.content)


class AislamientoEntrenamientoTestCase(BaseEntrenamientoTestCase):

    def test_no_se_ven_los_ejercicios_de_otro_gimnasio(self):
        self._crear_ejercicio()
        _t, _r, ajeno = _crear_tenant_con_usuario(
            'entrenajeno', 'EA', 'admin@entrenajeno.example.com',
            permisos=('rutinas.gestionar',),
        )

        respuesta = self.client.get(
            '/api/ejercicios/?incluir_inactivos=1',
            HTTP_HOST='entrenajeno.testserver', **_cabecera_token(ajeno),
        )

        self.assertEqual(len(respuesta.json()['results']), 0)
