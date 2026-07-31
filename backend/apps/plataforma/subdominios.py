"""Generación y validación de subdominios de tenant.

El subdominio es la URL con la que el gimnasio entra al sistema
(``migimnasio.miapp.com``), así que es marca visible y no un identificador
interno. Cambiarlo después rompe los favoritos del cliente, las sesiones
guardadas en los navegadores del mostrador y cualquier enlace que haya
compartido: conviene acertar a la primera.

Por eso este módulo *propone* un subdominio a partir del nombre, pero quien
da de alta el gimnasio puede imponer el suyo. La propuesta ahorra trabajo
cuando el nombre da un resultado decente; la elección manual existe porque a
menudo no lo da ("Gimnasio Power Fit" propone ``gimnasio-power-fit``, cuando
lo que quieres es ``powerfit``).

La validación, en cambio, se aplica SIEMPRE, venga el subdominio de donde
venga.
"""

import re

from django.utils.text import slugify

# Subdominios que ningún gimnasio puede ocupar porque son —o serán—
# infraestructura de la plataforma. Sin esta lista se podía crear un gimnasio
# con el subdominio "api", y entonces api.miapp.com sería a la vez el API y un
# cliente: el enrutado colisiona y los fallos son difíciles de rastrear.
SUBDOMINIOS_RESERVADOS = frozenset({
    # Infraestructura y servicios
    'www', 'api', 'admin', 'app', 'static', 'assets', 'cdn', 'media',
    'mail', 'smtp', 'imap', 'pop', 'ftp', 'ns', 'ns1', 'ns2', 'mx',
    # Entornos
    'dev', 'test', 'staging', 'pre', 'prod', 'demo', 'sandbox', 'local',
    # Cara pública y soporte
    'blog', 'docs', 'ayuda', 'soporte', 'status', 'estado', 'panel',
    'cuenta', 'cuentas', 'login', 'signup', 'registro', 'pago', 'pagos',
    'facturacion', 'billing', 'seguridad', 'security',
})

# El esquema impone: ^[a-z0-9][a-z0-9-]{1,40}$ -> entre 2 y 41 caracteres,
# empezando por letra o dígito. Se replica aquí para poder dar un mensaje
# útil antes de que reviente la restricción de la base.
LONGITUD_MINIMA = 2
LONGITUD_MAXIMA = 41

# Réplica exacta del CHECK `ck_tenants_subdominio` del esquema. Se valida
# contra este patrón y NO con `slugify`: slugify conserva los guiones bajos
# ("power_fit" le parece válido) y la base no los admite, así que un
# subdominio con guion bajo habría pasado la validación de la aplicación para
# reventar después contra la restricción de PostgreSQL.
PATRON_SUBDOMINIO = re.compile(r'^[a-z0-9][a-z0-9-]{1,40}$')


class SubdominioInvalido(ValueError):
    """El subdominio no se puede usar. El mensaje explica por qué."""


def proponer_subdominio(nombre_comercial):
    """Deriva un subdominio a partir del nombre del gimnasio.

    ``slugify`` se encarga de las tildes y la ñ ("Gimnasio El Peñón" ->
    ``gimnasio-el-penon``) y de los símbolos ("Fit & Strong" ->
    ``fit-strong``).

    :raises SubdominioInvalido: si del nombre no sale nada utilizable (por
        ejemplo, un nombre compuesto solo de símbolos). En ese caso hay que
        indicar el subdominio a mano; no tiene sentido inventar uno.
    """
    propuesta = slugify(nombre_comercial or '', allow_unicode=False)
    # slugify conserva los guiones bajos y el esquema no los admite.
    propuesta = propuesta.replace('_', '-')
    propuesta = propuesta[:LONGITUD_MAXIMA].strip('-')

    if len(propuesta) < LONGITUD_MINIMA:
        raise SubdominioInvalido(
            f'No se puede derivar un subdominio del nombre "{nombre_comercial}". '
            'Indícalo a mano con --subdominio.'
        )
    return propuesta


def validar_subdominio(subdominio):
    """Comprueba formato y palabras reservadas. No consulta la base de datos.

    :raises SubdominioInvalido: con un mensaje que dice qué corregir.
    """
    if not subdominio:
        raise SubdominioInvalido('El subdominio no puede estar vacío.')

    if subdominio in SUBDOMINIOS_RESERVADOS:
        raise SubdominioInvalido(
            f'El subdominio "{subdominio}" está reservado para la plataforma '
            'y no puede asignarse a un gimnasio. Elige otro.'
        )

    if not (LONGITUD_MINIMA <= len(subdominio) <= LONGITUD_MAXIMA):
        raise SubdominioInvalido(
            f'El subdominio debe tener entre {LONGITUD_MINIMA} y '
            f'{LONGITUD_MAXIMA} caracteres; "{subdominio}" tiene {len(subdominio)}.'
        )

    if not PATRON_SUBDOMINIO.match(subdominio):
        raise SubdominioInvalido(
            f'El subdominio "{subdominio}" no es válido: solo se admiten '
            'minúsculas, números y guiones, empezando por letra o número.'
        )


def buscar_disponible(base, esta_ocupado, intentos=99):
    """Devuelve ``base`` si está libre, o ``base-2``, ``base-3``… si no.

    Solo debe usarse con subdominios PROPUESTOS automáticamente. Cuando el
    operador escribe uno a mano y ya está ocupado, lo correcto es fallar y
    decírselo: elegir ``powerfit-2`` en su lugar le daría una URL que no pidió
    y de la que probablemente no se entere hasta que el cliente se queje.

    :param esta_ocupado: función ``(subdominio) -> bool``.
    """
    if not esta_ocupado(base):
        return base

    for numero in range(2, intentos + 1):
        sufijo = f'-{numero}'
        # Se recorta la base para que el sufijo quepa dentro del límite.
        candidato = f'{base[:LONGITUD_MAXIMA - len(sufijo)].rstrip("-")}{sufijo}'
        if not esta_ocupado(candidato):
            return candidato

    raise SubdominioInvalido(
        f'No se encontró un subdominio libre a partir de "{base}". '
        'Indícalo a mano con --subdominio.'
    )
