"""Qué sedes puede VER cada usuario.

## El problema que resuelve

RLS aísla por TENANT, no por sede: todas las sedes de un gimnasio comparten
las mismas políticas. Eso está bien para los clientes —un socio pertenece al
gimnasio y puede entrenar donde quiera— pero no para el dinero: hasta ahora
un recepcionista de Sede Norte podía consultar la caja, las ventas y la
cartera de Sede Principal sencillamente pidiéndolas.

``usuarios_sedes`` existía y solo se usaba para ELEGIR una sede por defecto
al registrar algo. Aquí pasa a acotar también la LECTURA.

## Quién ve qué

* Con ``config.sedes`` (el rol ``administrador``, el dueño): TODAS las sedes
  y el consolidado. Lo pide §2.1 del encargo -- "todas las sedes...
  reportes consolidados"-- y es lo que necesita quien es dueño del negocio.
* Cualquier otro: solo las sedes a las que está asignado.
* Sin ninguna sede asignada: NADA. Es coherente con que tampoco pueda vender
  ni cobrar, y la pantalla lo explica en vez de enseñar ceros sin motivo.

## Por qué 403 y no una lista vacía

Pedir una sede ajena devuelve 403, no cero resultados. Un cero silencioso se
lee como "ese día no hubo ventas", que es una respuesta falsa a una pregunta
legítima; el 403 dice la verdad: no es tuya.
"""
from rest_framework.exceptions import PermissionDenied

from .permissions import usuario_tiene_permiso

#: Permiso que distingue al dueño del resto. Se mira el PERMISO y no el
#: nombre del rol porque los roles son configurables: llamarse
#: "administrador" no garantiza nada, tener `config.sedes` sí.
PERMISO_TODAS_LAS_SEDES = 'config.sedes'


def sedes_visibles(request):
    """Ids de sede que este usuario puede consultar.

    Devuelve ``None`` cuando puede verlas TODAS (el dueño): así quien llama
    distingue "sin restricción" de "restringido a ninguna", que son casos
    opuestos y confundirlos enseñaría el gimnasio entero a quien no debe.
    """
    usuario = request.user
    if usuario_tiene_permiso(usuario, PERMISO_TODAS_LAS_SEDES, request=request):
        return None

    # Import perezoso: `apps.core` se carga muy temprano.
    from apps.organizacion.models import UsuarioSede

    return list(
        UsuarioSede.objects.filter(usuario=usuario).values_list('sede_id', flat=True),
    )


def sede_pedida(request, parametro='sede'):
    """Lee ``?sede=`` y comprueba que el usuario pueda verla.

    Devuelve el id como entero, o ``None`` si no se pidió ninguna.
    """
    valor = request.query_params.get(parametro)
    if not valor:
        return None

    try:
        sede_id = int(valor)
    except (TypeError, ValueError):
        raise PermissionDenied('Sede no válida.')

    permitidas = sedes_visibles(request)
    if permitidas is not None and sede_id not in permitidas:
        raise PermissionDenied(
            'No tienes acceso a esa sede. Pídeselo al administrador del gimnasio.',
        )
    return sede_id


def acotar_por_sede(request, qs, campo='sede_id', parametro='sede'):
    """Acota un queryset a lo que este usuario puede ver, respetando además
    el filtro ``?sede=`` cuando venga.

    ``campo`` permite acotar por una relación (``venta__sede_id``) cuando la
    tabla no lleva la sede directamente.
    """
    sede = sede_pedida(request, parametro)
    if sede is not None:
        return qs.filter(**{campo: sede})

    permitidas = sedes_visibles(request)
    if permitidas is None:
        return qs
    # Lista vacía -> `__in=[]` no devuelve nada, que es exactamente lo que
    # debe ver quien no tiene ninguna sede asignada.
    return qs.filter(**{f'{campo}__in': permitidas})
