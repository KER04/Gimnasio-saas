"""Utilidades de serialización compartidas entre apps.

CRÍTICO (§2.1 de los requisitos): ``costo`` y ``costo_unitario`` son datos
financieros que el recepcionista NO debe ver. La ocultación se hace en el
serializer (``to_representation``), nunca dejada al frontend: un cliente HTTP
que no sea el Angular oficial (curl, Postman, un script) recibiría igualmente
el campo si solo se ocultara en la interfaz.

El campo se ELIMINA del diccionario de salida; no se serializa como ``null``,
porque un ``null`` explícito seguiría siendo una fuga -- confirma la
existencia y la "forma" del campo.

Vive aquí, y no en la app de ventas donde nació, porque lo aplican al menos
dos apps (``ventas`` e ``inventario``) sobre los mismos campos. Tener dos
copias de esta condición es exactamente el tipo de duplicado que acaba
divergiendo y filtrando un costo por el lado que se olvidó actualizar.
"""
from apps.core.permissions import usuario_tiene_permiso

#: Campos que solo debe ver quien tenga el permiso ``costos.ver``.
CAMPOS_SOLO_COSTOS_VER = ('costo', 'costo_unitario')


def ocultar_campos_de_costo(data, request):
    """Elimina de ``data`` los campos de costo si el usuario de ``request``
    no tiene ``costos.ver``. Devuelve el mismo dict, ya filtrado."""
    usuario = getattr(request, 'user', None) if request is not None else None
    if not usuario_tiene_permiso(usuario, 'costos.ver', request=request):
        for campo in CAMPOS_SOLO_COSTOS_VER:
            data.pop(campo, None)
    return data
