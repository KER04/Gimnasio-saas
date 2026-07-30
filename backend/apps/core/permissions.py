"""Permisos por rol para la API (Parte A del encargo de ventas/POS).

El catálogo de permisos vive en la tabla global ``permisos`` (sembrada por
``apps.core`` migración 0001) y se asigna a cada rol del tenant mediante
``roles_permisos`` (``apps.organizacion.RolPermiso``). Este módulo traduce esa
relación en una ``BasePermission`` de DRF parametrizable por vista:

    class VentaViewSet(viewsets.GenericViewSet):
        permission_classes = [TienePermiso]
        permiso_requerido = 'ventas.registrar'
        permisos_por_accion = {'anular': 'ventas.anular'}

``permisos_por_accion`` (opcional) tiene prioridad sobre ``permiso_requerido``
para la ``view.action`` actual (nombre de acción de un ``ViewSet``: 'list',
'create', 'retrieve', o el nombre de un ``@action`` personalizado). Si la
acción no aparece en ese diccionario, se usa ``permiso_requerido`` como
permiso por defecto de toda la vista.

## Caché por petición

``usuario_tiene_permiso`` consulta ``roles_permisos`` filtrando por
``rol_id``. Una vista puede llamarla varias veces durante la MISMA petición
(la propia ``TienePermiso.has_permission`` una vez, y luego cada serializer
que oculta costos otra vez por cada línea de venta serializada). Para no
repetir esa consulta en cada verificación, el conjunto de códigos de permiso
del rol se cachea en un atributo del propio ``request`` (``_ker_permisos_rol``,
un dict ``{rol_id: {codigos}}``) en vez de usar ``functools.lru_cache``: un
caché de proceso (lru_cache) sobreviviría más allá de la petición y de la
prueba que lo llenó -- en la batería de tests, dos tenants distintos pueden
reutilizar el mismo ``rol_id`` autoincremental entre métodos de prueba, y un
resultado cacheado de una prueba anterior contaminaría la siguiente. Cachear
en ``request`` vive y muere con la petición, así que no hay ese riesgo.
"""
from rest_framework.permissions import BasePermission

_CACHE_ATTR = '_ker_permisos_rol'


def _codigos_permiso_del_rol(rol_id, using='default'):
    from apps.organizacion.models import RolPermiso

    return set(
        RolPermiso.objects.using(using)
        .filter(rol_id=rol_id)
        .values_list('permiso__codigo', flat=True)
    )


def usuario_tiene_permiso(usuario, codigo, request=None, using='default'):
    """``True`` si el rol de ``usuario`` tiene el permiso ``codigo``.

    Reutilizable desde serializers (p. ej. para ocultar ``costo_unitario`` a
    quien no tenga ``costos.ver``) y desde ``TienePermiso``. Si se pasa
    ``request``, el resultado se cachea allí para no repetir la consulta a
    ``roles_permisos`` dentro de la misma petición.

    Devuelve ``False`` (nunca lanza) ante cualquier usuario no autenticado o
    sin rol -- falla cerrado.
    """
    if usuario is None or not getattr(usuario, 'is_authenticated', False):
        return False

    rol_id = getattr(usuario, 'rol_id', None)
    if rol_id is None:
        return False

    if request is not None:
        cache = getattr(request, _CACHE_ATTR, None)
        if cache is None:
            cache = {}
            setattr(request, _CACHE_ATTR, cache)
        if rol_id not in cache:
            cache[rol_id] = _codigos_permiso_del_rol(rol_id, using=using)
        return codigo in cache[rol_id]

    return codigo in _codigos_permiso_del_rol(rol_id, using=using)


class TienePermiso(BasePermission):
    """Exige que el rol del usuario autenticado tenga un permiso concreto.

    La vista declara el permiso requerido de una de estas dos formas
    (``permisos_por_accion`` gana si la acción actual aparece en él):

        permiso_requerido = 'ventas.registrar'
        permisos_por_accion = {'create': 'ventas.registrar', 'destroy': 'ventas.anular'}

    Si la vista no declara ninguna de las dos, esta clase no restringe nada
    (devuelve ``True``) -- deja que otras permission_classes decidan.
    """

    message = 'No tienes permiso para realizar esta acción.'

    def _permiso_para_vista(self, view):
        accion = getattr(view, 'action', None)
        permisos_por_accion = getattr(view, 'permisos_por_accion', None)
        if accion is not None and permisos_por_accion and accion in permisos_por_accion:
            return permisos_por_accion[accion]
        return getattr(view, 'permiso_requerido', None)

    def has_permission(self, request, view):
        codigo = self._permiso_para_vista(view)
        if codigo is None:
            return True

        usuario = getattr(request, 'user', None)
        if usuario is None or not getattr(usuario, 'is_authenticated', False):
            self.message = 'Debes iniciar sesión para realizar esta acción.'
            return False

        if not usuario_tiene_permiso(usuario, codigo, request=request):
            self.message = f'No tienes el permiso "{codigo}" requerido para realizar esta acción.'
            return False

        return True
