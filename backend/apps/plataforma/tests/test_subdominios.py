"""Pruebas de la generación y validación de subdominios de tenant.

Lógica pura salvo `buscar_disponible`, que recibe la comprobación de
ocupación como parámetro: no hace falta base de datos.
"""

from django.test import SimpleTestCase

from apps.plataforma.subdominios import (
    LONGITUD_MAXIMA,
    SubdominioInvalido,
    buscar_disponible,
    proponer_subdominio,
    validar_subdominio,
)


class ProponerSubdominioTestCase(SimpleTestCase):

    def test_deriva_del_nombre_comercial(self):
        self.assertEqual(proponer_subdominio('Gimnasio Power Fit'), 'gimnasio-power-fit')

    def test_quita_tildes_y_enes(self):
        """El CHECK del esquema solo admite [a-z0-9-]: una ñ o una tilde sin
        transliterar reventaría contra la base."""
        self.assertEqual(proponer_subdominio('Gimnasio El Peñón'), 'gimnasio-el-penon')

    def test_quita_simbolos(self):
        self.assertEqual(proponer_subdominio('Fit & Strong Gym'), 'fit-strong-gym')

    def test_admite_empezar_por_numero(self):
        self.assertEqual(proponer_subdominio('24/7 Gym'), '247-gym')

    def test_recorta_al_maximo_sin_dejar_guion_final(self):
        propuesta = proponer_subdominio('Gimnasio ' + 'muy largo ' * 10)
        self.assertLessEqual(len(propuesta), LONGITUD_MAXIMA)
        self.assertFalse(propuesta.endswith('-'))

    def test_nombre_sin_nada_utilizable_falla_en_vez_de_inventar(self):
        with self.assertRaises(SubdominioInvalido):
            proponer_subdominio('!!! ¿¿¿ ---')


class ValidarSubdominioTestCase(SimpleTestCase):

    def test_acepta_uno_correcto(self):
        validar_subdominio('powerfit')  # no debe lanzar

    def test_rechaza_reservados(self):
        """Sin esto se podía crear un gimnasio con el subdominio 'api', y
        api.miapp.com sería a la vez el API y un cliente."""
        for reservado in ('api', 'www', 'admin', 'app', 'static', 'mail'):
            with self.subTest(reservado=reservado):
                with self.assertRaises(SubdominioInvalido):
                    validar_subdominio(reservado)

    def test_rechaza_mayusculas_y_espacios(self):
        for invalido in ('PowerFit', 'power fit', 'power_fit', 'poder!'):
            with self.subTest(invalido=invalido):
                with self.assertRaises(SubdominioInvalido):
                    validar_subdominio(invalido)

    def test_rechaza_demasiado_corto_o_largo(self):
        with self.assertRaises(SubdominioInvalido):
            validar_subdominio('a')
        with self.assertRaises(SubdominioInvalido):
            validar_subdominio('a' * (LONGITUD_MAXIMA + 1))

    def test_rechaza_vacio(self):
        with self.assertRaises(SubdominioInvalido):
            validar_subdominio('')


class BuscarDisponibleTestCase(SimpleTestCase):

    def test_devuelve_la_base_si_esta_libre(self):
        self.assertEqual(buscar_disponible('powerfit', lambda s: False), 'powerfit')

    def test_anade_sufijo_si_esta_ocupada(self):
        ocupados = {'powerfit'}
        self.assertEqual(buscar_disponible('powerfit', lambda s: s in ocupados), 'powerfit-2')

    def test_sigue_incrementando(self):
        ocupados = {'powerfit', 'powerfit-2', 'powerfit-3'}
        self.assertEqual(buscar_disponible('powerfit', lambda s: s in ocupados), 'powerfit-4')

    def test_el_sufijo_no_desborda_el_limite(self):
        base = 'a' * LONGITUD_MAXIMA
        resultado = buscar_disponible(base, lambda s: s == base)
        self.assertLessEqual(len(resultado), LONGITUD_MAXIMA)
        self.assertTrue(resultado.endswith('-2'))
