"""Recuentos por gimnasio para el panel del proveedor.

## Por qué esto no es un solo ``annotate``

Las tablas de negocio están bajo RLS: sus políticas comparan
``tenant_id = fn_tenant_actual()``, y el rol de la aplicación (``keradmin``)
no tiene BYPASSRLS. Sin tenant fijado no se ve nada; con uno fijado se ve ese.
No hay consulta única que cuente los clientes de todos los gimnasios.

## Por qué NO se usa una vista que se salte RLS

Fue el primer intento: una vista sin ``security_invoker`` se evalúa con los
privilegios de su dueño y, si el dueño es ``postgres``, atraviesa RLS y
permite agregar todos los tenants de una vez.

Se descartó al probarlo. El dueño de la vista es quien ejecutó la migración:
``postgres`` en desarrollo y producción (``migrate --database=ddl``), pero
``keradmin`` en la base que crea el test runner. Con ``keradmin`` de dueño la
vista SÍ respeta RLS y devuelve CEROS -- sin error, sin aviso, solo números
falsos. Es decir: un comportamiento del que depende toda la pantalla quedaba
sujeto a quién había lanzado un comando, fallaba en silencio y no se podía
probar. Contar por tenant es más consultas, pero es correcto en todos los
entornos y se puede verificar.

## Coste

Una transacción corta por gimnasio de la página (20 como mucho). Es una
pantalla interna que abre el personal del proveedor de vez en cuando, no un
listado de cara al público.
"""
from django.db.models import Count, Max, Q

from apps.clientes.models import Cliente
from apps.core.tenant import tenant_context
from apps.membresias.models import Membresia
from apps.organizacion.models import Sede, Usuario
from apps.ventas.models import Venta


def _contar(tenant):
    """Recuentos de UN gimnasio, dentro de su propio contexto RLS."""
    with tenant_context(tenant.id):
        return {
            'sedes': Sede.objects.filter(activa=True).count(),
            'usuarios': Usuario.objects.filter(activo=True).count(),
            'clientes': Cliente.objects.filter(activo=True, eliminado_en__isnull=True).count(),
            # Vigentes HOY. Se compara contra la fecha del servidor y no
            # contra la del gimnasio: aquí un día de desfase no cambia
            # ninguna decisión, y traer la zona horaria de cada tenant a
            # Python solo para un contador informativo no compensa.
            'membresias_activas': Membresia.objects.filter(
                fecha_fin__gte=_hoy(),
            ).exclude(estado=Membresia.EstadoMembresia.CANCELADA).count(),
            'ultima_venta': Venta.objects.aggregate(ultima=Max('fecha_hora'))['ultima'],
        }


def _hoy():
    from django.utils import timezone
    return timezone.localdate()


def anexar_recuentos(tenants):
    """Pega los recuentos a cada tenant como atributos ``resumen_*``.

    Se escriben en el objeto en lugar de devolverse aparte para que el
    serializer los lea igual que si fueran anotaciones del queryset.

    IMPORTANTE: al terminar, ``app.tenant_id`` queda fijado al último tenant
    recorrido -- ``set_config(..., true)`` vive hasta el final de la
    transacción EXTERNA, no del ``with`` (está documentado en
    ``apps.core.tenant``). Por eso esta función es lo ÚLTIMO que debe tocar
    tablas de negocio en una petición: cualquier consulta posterior vería los
    datos de ese último gimnasio. Las vistas del panel solo la llaman para
    serializar y no consultan nada más después.
    """
    for tenant in tenants:
        for campo, valor in _contar(tenant).items():
            setattr(tenant, f'resumen_{campo}', valor)
