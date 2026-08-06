"""Batería de la API de inventario: productos, categorías y kardex.

Sigue el patrón de ``apps/ventas/tests/test_api.py``: ``TestCase`` +
``databases = {'default', 'ddl'}``, tokens construidos a mano y
``HTTP_HOST='<subdominio>.testserver'`` para que ``TenantMiddleware`` resuelva
el tenant. Reutiliza ``crear_escenario_pos`` de ventas en vez de duplicar una
fábrica: ya siembra un producto con stock, un rol admin con
``inventario.gestionar``/``costos.ver`` y un recepcionista SIN ninguno de los
dos, que es justo lo que hace falta para probar los límites de permiso.

Lo que se protege aquí:

- El borrado es LÓGICO. ``DetalleVenta.producto`` es ``PROTECT``: un borrado
  real reventaría en cuanto el producto se haya vendido una vez.
- Las existencias NUNCA se escriben directamente. Solo se mueven insertando
  en el kardex, y es el disparador ``fn_actualizar_stock_sede`` quien
  actualiza ``stock_sedes`` y calcula ``saldo_resultante``.
- Desde esta API solo se pueden registrar ``entrada_compra`` y
  ``ajuste_manual``: permitir ``salida_venta`` dejaría fabricar movimientos
  de venta sin venta detrás.
- ``costo`` desaparece de la respuesta para quien no tenga ``costos.ver``.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tenant import tenant_context
from apps.inventario.models import CategoriaProducto, MovimientoInventario, Producto, StockSede
from apps.ventas.tests.factories import crear_escenario_pos

_ALLOWED_HOSTS_PRUEBA = ['testserver', '.testserver']


def _token_para(usuario):
    access = AccessToken.for_user(usuario)
    access['tenant_id'] = usuario.tenant_id
    return str(access)


def _auth_headers(usuario, subdominio):
    return {
        'HTTP_HOST': f'{subdominio}.testserver',
        'HTTP_AUTHORIZATION': f'Bearer {_token_para(usuario)}',
    }


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class ProductoCrudTestCase(TestCase):
    """CRUD del catálogo: alta, edición y baja lógica."""

    databases = {'default', 'ddl'}
    SUBDOMINIO = 'inv-crud'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'IC')

    def _headers(self, usuario=None):
        return _auth_headers(usuario or self.datos['usuario_admin'], self.SUBDOMINIO)

    def test_crear_producto(self):
        respuesta = self.client.post(
            '/api/productos/',
            {
                'nombre': 'Barra energética',
                'categoria_producto': self.datos['categoria_producto'].id,
                'precio_venta': '4500.00',
                'costo': '2000.00',
            },
            content_type='application/json',
            **self._headers(),
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        with tenant_context(self.datos['tenant'].id):
            producto = Producto.objects.get(nombre='Barra energética')
        self.assertTrue(producto.activo)
        self.assertEqual(producto.precio_venta, Decimal('4500.00'))

    def test_precio_negativo_es_400(self):
        respuesta = self.client.post(
            '/api/productos/',
            {
                'nombre': 'Imposible',
                'categoria_producto': self.datos['categoria_producto'].id,
                'precio_venta': '-1.00',
            },
            content_type='application/json',
            **self._headers(),
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('precio_venta', respuesta.json())

    def test_borrado_es_logico_y_conserva_la_fila(self):
        """La fila sigue existiendo con ``activo=False``: el histórico de
        ventas la referencia y ``PROTECT`` impediría borrarla de verdad."""
        producto = self.datos['producto']

        respuesta = self.client.delete(f'/api/productos/{producto.id}/', **self._headers())

        self.assertEqual(respuesta.status_code, 204)
        with tenant_context(self.datos['tenant'].id):
            producto.refresh_from_db()
        self.assertFalse(producto.activo)

    def test_el_listado_oculta_los_inactivos_salvo_que_se_pidan(self):
        producto = self.datos['producto']
        self.client.delete(f'/api/productos/{producto.id}/', **self._headers())

        visibles = self.client.get(
            f'/api/productos/?sede_id={self.datos["sede"].id}', **self._headers(),
        ).json()['results']
        self.assertNotIn(producto.id, [p['id'] for p in visibles])

        con_inactivos = self.client.get(
            f'/api/productos/?sede_id={self.datos["sede"].id}&incluir_inactivos=1', **self._headers(),
        ).json()['results']
        self.assertIn(producto.id, [p['id'] for p in con_inactivos])

    def test_un_producto_dado_de_baja_se_puede_editar_y_reactivar(self):
        """La baja lógica tiene que ser reversible desde el formulario.

        El `get_queryset` filtraba `activo=True` en TODAS las acciones, no
        solo en el listado. Como el formulario guarda con un PATCH sin
        `?incluir_inactivos`, la fila quedaba escondida y la respuesta era un
        404: la casilla "Activo" no podía volver a marcarse una vez desmarcada.
        """
        producto = self.datos['producto']
        self.assertEqual(self.client.delete(f'/api/productos/{producto.id}/', **self._headers()).status_code, 204)

        # El detalle responde: sin esto el formulario de edición ni se abriría.
        self.assertEqual(self.client.get(f'/api/productos/{producto.id}/', **self._headers()).status_code, 200)

        respuesta = self.client.patch(
            f'/api/productos/{producto.id}/', {'activo': True},
            content_type='application/json', **self._headers(),
        )
        self.assertEqual(respuesta.status_code, 200, respuesta.content)

        with tenant_context(self.datos['tenant'].id):
            producto.refresh_from_db()
        self.assertTrue(producto.activo)

        # Y vuelve al listado normal, que es el que ve el POS.
        visibles = self.client.get(
            f'/api/productos/?sede_id={self.datos["sede"].id}', **self._headers(),
        ).json()['results']
        self.assertIn(producto.id, [p['id'] for p in visibles])

    def test_busca_palabra_a_palabra(self):
        """"whey choco" encuentra "Proteína Whey Chocolate": cada palabra debe
        aparecer, no la cadena entera como subcadena literal."""
        with tenant_context(self.datos['tenant'].id):
            Producto.objects.create(
                tenant=self.datos['tenant'],
                categoria_producto=self.datos['categoria_producto'],
                nombre='Proteína Whey Chocolate',
                precio_venta=Decimal('90000.00'),
            )

        resultados = self.client.get(
            f'/api/productos/?sede_id={self.datos["sede"].id}&buscar=whey%20choco', **self._headers(),
        ).json()['results']

        self.assertEqual([p['nombre'] for p in resultados], ['Proteína Whey Chocolate'])

    def test_el_stock_sale_de_la_sede_consultada(self):
        """Sin ``sede_id`` el stock es ``None`` -- que significa "no se
        preguntó por ninguna sede", no "no hay existencias"."""
        producto = self.datos['producto']

        con_sede = self.client.get(
            f'/api/productos/?sede_id={self.datos["sede"].id}', **self._headers(),
        ).json()['results']
        self.assertEqual(next(p['stock'] for p in con_sede if p['id'] == producto.id), '100.00')

        # La segunda sede del mismo tenant no recibió ninguna entrada.
        otra_sede = self.client.get(
            f'/api/productos/?sede_id={self.datos["sede2"].id}', **self._headers(),
        ).json()['results']
        self.assertEqual(next(p['stock'] for p in otra_sede if p['id'] == producto.id), '0')

        sin_sede = self.client.get('/api/productos/', **self._headers()).json()['results']
        self.assertIsNone(next(p['stock'] for p in sin_sede if p['id'] == producto.id))


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class PermisosInventarioTestCase(TestCase):
    """Leer exige ``inventario.ver``; escribir, ``inventario.gestionar``. El
    costo solo lo ve quien tenga ``costos.ver``."""

    databases = {'default', 'ddl'}
    SUBDOMINIO = 'inv-perm'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'IP')

    def test_recepcion_puede_leer_pero_no_crear(self):
        recepcion = self.datos['usuario_recepcion']
        headers = _auth_headers(recepcion, self.SUBDOMINIO)

        self.assertEqual(self.client.get('/api/productos/', **headers).status_code, 200)

        respuesta = self.client.post(
            '/api/productos/',
            {
                'nombre': 'No debería crearse',
                'categoria_producto': self.datos['categoria_producto'].id,
                'precio_venta': '1000.00',
            },
            content_type='application/json',
            **headers,
        )
        self.assertEqual(respuesta.status_code, 403)

    def test_el_costo_se_oculta_sin_permiso(self):
        """No se devuelve como ``null``: se elimina del diccionario. Un
        ``null`` explícito seguiría confirmando la existencia del campo."""
        admin = self.client.get('/api/productos/', **_auth_headers(
            self.datos['usuario_admin'], self.SUBDOMINIO,
        )).json()['results'][0]
        self.assertIn('costo', admin)

        recepcion = self.client.get('/api/productos/', **_auth_headers(
            self.datos['usuario_recepcion'], self.SUBDOMINIO,
        )).json()['results'][0]
        self.assertNotIn('costo', recepcion)


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class MovimientosInventarioTestCase(TestCase):
    """El kardex y su disparador: toda existencia se mueve por aquí."""

    databases = {'default', 'ddl'}
    SUBDOMINIO = 'inv-mov'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'IM')

    def _headers(self):
        return _auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO)

    def _stock(self):
        with tenant_context(self.datos['tenant'].id):
            return StockSede.objects.get(
                producto=self.datos['producto'], sede=self.datos['sede'],
            ).cantidad

    def _movimiento(self, **campos):
        cuerpo = {
            'producto_id': self.datos['producto'].id,
            'sede_id': self.datos['sede'].id,
            **campos,
        }
        return self.client.post(
            '/api/movimientos-inventario/', cuerpo, content_type='application/json', **self._headers(),
        )

    def test_entrada_suma_y_el_disparador_calcula_el_saldo(self):
        respuesta = self._movimiento(tipo='entrada_compra', cantidad='25', costo_unitario='30000.00')

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        # El saldo lo rellena el disparador BEFORE INSERT, no la aplicación:
        # el cero que envía el servicio nunca llega a persistirse.
        self.assertEqual(respuesta.json()['saldo_resultante'], '125.00')
        self.assertEqual(self._stock(), Decimal('125.00'))

    def test_ajuste_negativo_descuenta(self):
        respuesta = self._movimiento(tipo='ajuste_manual', cantidad='-10', motivo='Merma por caducidad')

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertEqual(self._stock(), Decimal('90.00'))

    def test_ajuste_sin_motivo_es_400(self):
        """Un ajuste sin motivo es inauditable; lo exigen el servicio y un
        CHECK de la base. Se traduce a 400, nunca a un 500."""
        respuesta = self._movimiento(tipo='ajuste_manual', cantidad='-1')

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('motivo', respuesta.json()['detail'].lower())
        self.assertEqual(self._stock(), Decimal('100.00'))

    def test_entrada_con_cantidad_negativa_es_400(self):
        respuesta = self._movimiento(tipo='entrada_compra', cantidad='-5')

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self._stock(), Decimal('100.00'))

    def test_cantidad_cero_es_400(self):
        respuesta = self._movimiento(tipo='ajuste_manual', cantidad='0', motivo='Nada')

        self.assertEqual(respuesta.status_code, 400)

    def test_no_se_pueden_fabricar_salidas_de_venta(self):
        """``salida_venta`` y ``reverso_anulacion`` los emite la venta. Desde
        esta API se rechazan: si no, se podrían inventar movimientos de venta
        sin una venta detrás, rompiendo la trazabilidad del kardex."""
        respuesta = self._movimiento(tipo='salida_venta', cantidad='-1')

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self._stock(), Decimal('100.00'))

    def test_no_puede_dejar_el_stock_negativo(self):
        """Lo impide el disparador con un RAISE EXCEPTION, y se traduce a 400
        con el mensaje legible de PostgreSQL."""
        respuesta = self._movimiento(tipo='ajuste_manual', cantidad='-500', motivo='Conteo físico')

        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self._stock(), Decimal('100.00'))

    def test_el_kardex_es_inmutable(self):
        """Solo listar y crear: los errores se corrigen con un movimiento
        inverso, no reescribiendo el pasado."""
        movimiento = self._movimiento(
            tipo='entrada_compra', cantidad='5', costo_unitario='30000.00',
        ).json()

        for metodo in (self.client.put, self.client.patch, self.client.delete):
            respuesta = metodo(
                f'/api/movimientos-inventario/{movimiento["id"]}/', **self._headers(),
            )
            self.assertIn(respuesta.status_code, (404, 405))


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class CategoriaProductoTestCase(TestCase):
    databases = {'default', 'ddl'}
    SUBDOMINIO = 'inv-cat'

    @classmethod
    def setUpTestData(cls):
        cls.datos = crear_escenario_pos(cls.SUBDOMINIO, 'ICat')

    def _headers(self):
        return _auth_headers(self.datos['usuario_admin'], self.SUBDOMINIO)

    def test_crear_y_dar_de_baja(self):
        creada = self.client.post(
            '/api/categorias-producto/', {'nombre': 'Bebidas frías'},
            content_type='application/json', **self._headers(),
        )
        self.assertEqual(creada.status_code, 201, creada.content)
        categoria_id = creada.json()['id']

        baja = self.client.delete(f'/api/categorias-producto/{categoria_id}/', **self._headers())
        self.assertEqual(baja.status_code, 204)

        # Baja lógica: la fila sigue ahí (Producto.categoria_producto es PROTECT).
        with tenant_context(self.datos['tenant'].id):
            self.assertFalse(CategoriaProducto.objects.get(pk=categoria_id).activa)

    def test_activa_no_es_obligatoria_al_crear(self):
        """El modelo la declara con ``db_default``, no con ``default`` de
        Python: sin ``required=False`` DRF la daría por obligatoria."""
        respuesta = self.client.post(
            '/api/categorias-producto/', {'nombre': 'Sin activa'},
            content_type='application/json', **self._headers(),
        )

        self.assertEqual(respuesta.status_code, 201, respuesta.content)
        self.assertTrue(respuesta.json()['activa'])

    def test_una_categoria_dada_de_baja_se_puede_reactivar(self):
        """Dar de baja no puede ser un viaje sin retorno.

        La API ya lo permitía, pero la pantalla pedía solo las activas: en
        cuanto se daba de baja una categoría desaparecía del panel y no había
        forma de volver a activarla sin tocar la base de datos. Este test fija
        las dos piezas de las que depende el arreglo: que `incluir_inactivos`
        la devuelva y que el PATCH la reactive.
        """
        creada = self.client.post(
            '/api/categorias-producto/', {'nombre': 'Temporada'},
            content_type='application/json', **self._headers(),
        )
        categoria_id = creada.json()['id']
        self.assertEqual(self.client.delete(f'/api/categorias-producto/{categoria_id}/', **self._headers()).status_code, 204)

        # Fuera del listado normal, dentro del que incluye las inactivas.
        normales = [c['id'] for c in self.client.get('/api/categorias-producto/', **self._headers()).json()['results']]
        self.assertNotIn(categoria_id, normales)
        con_bajas = self.client.get(
            '/api/categorias-producto/', {'incluir_inactivos': '1'}, **self._headers(),
        ).json()['results']
        self.assertIn(categoria_id, [c['id'] for c in con_bajas])

        reactivada = self.client.patch(
            f'/api/categorias-producto/{categoria_id}/', {'activa': True},
            content_type='application/json', **self._headers(),
        )
        self.assertEqual(reactivada.status_code, 200, reactivada.content)
        self.assertTrue(reactivada.json()['activa'])
        self.assertIn(
            categoria_id,
            [c['id'] for c in self.client.get('/api/categorias-producto/', **self._headers()).json()['results']],
        )


@override_settings(ALLOWED_HOSTS=_ALLOWED_HOSTS_PRUEBA)
class AislamientoInventarioTestCase(TestCase):
    """Un tenant no ve el inventario de otro: lo impone RLS, no la vista."""

    databases = {'default', 'ddl'}

    @classmethod
    def setUpTestData(cls):
        cls.uno = crear_escenario_pos('inv-uno', 'IU')
        cls.otro = crear_escenario_pos('inv-otro', 'IO')

    def test_no_se_ve_el_producto_del_otro_tenant(self):
        listado = self.client.get(
            '/api/productos/', **_auth_headers(self.uno['usuario_admin'], 'inv-uno'),
        ).json()['results']

        ids = [p['id'] for p in listado]
        self.assertIn(self.uno['producto'].id, ids)
        self.assertNotIn(self.otro['producto'].id, ids)

    def test_no_se_puede_mover_stock_de_otro_tenant(self):
        respuesta = self.client.post(
            '/api/movimientos-inventario/',
            {
                'producto_id': self.otro['producto'].id,
                'sede_id': self.otro['sede'].id,
                'tipo': 'entrada_compra',
                'cantidad': '10',
            },
            content_type='application/json',
            **_auth_headers(self.uno['usuario_admin'], 'inv-uno'),
        )

        # El producto "no existe" para este tenant: RLS lo filtra antes.
        self.assertEqual(respuesta.status_code, 400)
        with tenant_context(self.otro['tenant'].id):
            self.assertEqual(
                MovimientoInventario.objects.filter(producto=self.otro['producto']).count(), 1,
            )
