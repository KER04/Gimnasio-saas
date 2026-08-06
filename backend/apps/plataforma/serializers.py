"""Serializers del panel del proveedor."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Suscripcion, Tenant, UsuarioPlataforma
from .subdominios import SubdominioInvalido, proponer_subdominio, validar_subdominio


class UsuarioPlataformaSerializer(serializers.ModelSerializer):
    """Quién soy. Nunca incluye ``password_hash``."""

    class Meta:
        model = UsuarioPlataforma
        fields = ('id', 'nombre', 'correo', 'rol', 'activo', 'creado_en')
        read_only_fields = fields


class LoginPlataformaSerializer(serializers.Serializer):
    correo = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})


class RefrescoPlataformaSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class _ResumenMixin:
    """Lee los recuentos que la vista anexa al tenant.

    Llegan como atributos puestos por ``TenantViewSet.get_queryset`` desde
    ``v_plataforma_resumen_tenants``. Si por lo que sea faltan, se devuelve
    ``None`` en vez de reventar: un panel a medias es mejor que un 500.
    """

    def _resumen(self, obj, campo):
        return getattr(obj, f'resumen_{campo}', None)


class TenantListaSerializer(serializers.ModelSerializer, _ResumenMixin):
    """Fila del listado de gimnasios.

    ``id`` no se expone: hacia fuera un tenant se identifica por
    ``uuid_publico``, que es justo para lo que existe esa columna (evitar que
    se puedan enumerar los clientes por id secuencial).
    """

    sedes = serializers.SerializerMethodField()
    usuarios = serializers.SerializerMethodField()
    clientes = serializers.SerializerMethodField()
    membresias_activas = serializers.SerializerMethodField()
    ultima_venta = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = (
            'uuid_publico', 'nombre_comercial', 'subdominio', 'estado', 'ciudad',
            'responsable', 'correo', 'fecha_alta',
            'sedes', 'usuarios', 'clientes', 'membresias_activas', 'ultima_venta',
        )
        read_only_fields = fields

    def get_sedes(self, obj):
        return self._resumen(obj, 'sedes')

    def get_usuarios(self, obj):
        return self._resumen(obj, 'usuarios')

    def get_clientes(self, obj):
        return self._resumen(obj, 'clientes')

    def get_membresias_activas(self, obj):
        return self._resumen(obj, 'membresias_activas')

    def get_ultima_venta(self, obj):
        return self._resumen(obj, 'ultima_venta')


class SuscripcionResumenSerializer(serializers.ModelSerializer):
    plan_nombre = serializers.CharField(source='plan_suscripcion.nombre', read_only=True)
    precio_por_sede = serializers.DecimalField(
        source='plan_suscripcion.precio_por_sede', max_digits=12, decimal_places=2, read_only=True,
    )
    ciclo = serializers.CharField(source='plan_suscripcion.ciclo', read_only=True)

    class Meta:
        model = Suscripcion
        fields = (
            'id', 'plan_nombre', 'precio_por_sede', 'ciclo',
            'fecha_inicio', 'fecha_fin', 'proximo_corte', 'dias_gracia', 'estado',
        )
        read_only_fields = fields


class TenantDetalleSerializer(TenantListaSerializer):
    """Ficha completa: añade la configuración y la suscripción vigente."""

    suscripcion = serializers.SerializerMethodField()

    class Meta(TenantListaSerializer.Meta):
        fields = TenantListaSerializer.Meta.fields + (
            'nit', 'telefono', 'logo_url',
            'zona_horaria', 'moneda', 'dias_aviso_vencimiento', 'minutos_antipassback',
            'fecha_cancelacion', 'fecha_purga_datos', 'creado_en', 'actualizado_en',
            'suscripcion',
        )
        read_only_fields = fields

    def get_suscripcion(self, obj):
        # La restricción `uq_suscripciones_vigente` garantiza como mucho una
        # vigente por tenant; si no hay ninguna, el gimnasio está sin contrato
        # y el panel debe poder decirlo.
        vigente = next(
            (s for s in obj.suscripciones.all() if s.estado == Suscripcion.EstadoSuscripcion.VIGENTE),
            None,
        )
        return None if vigente is None else SuscripcionResumenSerializer(vigente).data


def _validar_zona_horaria(valor):
    """La zona horaria no es decorativa: `v_membresias_estado` y
    `v_corte_diario` calculan CON ELLA qué día es en el gimnasio. Una cadena
    inválida haría fallar esas vistas en producción, no aquí, y el síntoma
    sería "las membresías vencen un día antes"."""
    try:
        ZoneInfo(valor)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        raise serializers.ValidationError(
            f'"{valor}" no es una zona horaria conocida. Usa el formato IANA, '
            'por ejemplo "America/Bogota".',
        )
    return valor


class CambiarPasswordPlataformaSerializer(serializers.Serializer):
    """Cambio de la contraseña propia en el panel.

    Se pide la actual por el mismo motivo que en el gimnasio: tener la sesión
    abierta no prueba ser la persona, y esta cuenta gobierna todos los
    gimnasios.
    """

    password_actual = serializers.CharField(write_only=True)
    password_nueva = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_password_actual(self, valor):
        if not self.context['request'].user.check_password(valor):
            raise serializers.ValidationError('La contraseña actual no es correcta.')
        return valor

    def validate(self, datos):
        if datos['password_actual'] == datos['password_nueva']:
            raise serializers.ValidationError({
                'password_nueva': 'La contraseña nueva debe ser distinta de la actual.',
            })
        return datos


class RestablecerPasswordSerializer(serializers.Serializer):
    """Restablecimiento, por soporte, de la contraseña de un usuario de un
    gimnasio.

    Pide ``usuario_id`` explícito y no adivina a quién: un gimnasio puede
    tener varios administradores, y elegir "el primero" convertiría una
    operación delicada en una lotería.

    NO exige escribir el subdominio, al contrario que el cambio de estado.
    Es deliberado: allí el riesgo es equivocarse de FILA en una tabla de
    gimnasios parecidos, mientras que aquí ya se está dentro de la ficha de
    un gimnasio y hay que señalar a una persona concreta, con su nombre y su
    correo a la vista. Añadir fricción a una operación de rescate que se hace
    con el cliente esperando al teléfono no compra seguridad, solo tiempo.
    """

    usuario_id = serializers.IntegerField()


class UsuarioDeGimnasioSerializer(serializers.Serializer):
    """Un usuario del gimnasio, visto desde el panel del proveedor.

    Solo lo justo para poder restablecerle la contraseña con conocimiento de
    causa. Nada de datos personales más allá del correo de trabajo.
    """

    id = serializers.IntegerField(read_only=True)
    nombre = serializers.CharField(read_only=True)
    correo = serializers.CharField(read_only=True)
    activo = serializers.BooleanField(read_only=True)
    rol = serializers.CharField(source='rol.nombre', read_only=True)


class TenantCrearSerializer(serializers.Serializer):
    """Alta de un gimnasio desde el panel.

    No es un ``ModelSerializer``: además del tenant hay que sembrar sede,
    roles, permisos, semillas y el usuario administrador, y ese trabajo lo
    hace `aprovisionamiento.aprovisionar_tenant`. Aquí solo se validan los
    datos de entrada.

    La contraseña NO se pide: la genera el servidor y se enseña una sola vez
    en la respuesta.
    """

    nombre_comercial = serializers.CharField(max_length=150)
    #: Opcional: si no viene, se propone a partir del nombre y se busca el
    #: primero libre. Una vez creado NO se puede cambiar (es la URL del
    #: cliente), por eso no aparece en `TenantConfiguracionSerializer`.
    subdominio = serializers.CharField(max_length=41, required=False, allow_blank=True)
    correo_admin = serializers.EmailField()
    nombre_sede = serializers.CharField(max_length=150, required=False, allow_blank=True)

    responsable = serializers.CharField(max_length=150, required=False, allow_blank=True)
    telefono = serializers.CharField(max_length=30, required=False, allow_blank=True)
    ciudad = serializers.CharField(max_length=100, required=False, allow_blank=True)
    nit = serializers.CharField(max_length=30, required=False, allow_blank=True)

    def validate_subdominio(self, valor):
        if not valor:
            return valor
        subdominio = valor.strip().lower()
        try:
            validar_subdominio(subdominio)
        except SubdominioInvalido as exc:
            raise serializers.ValidationError(str(exc))
        if Tenant.objects.filter(subdominio__iexact=subdominio).exists():
            # Se dice claramente que está ocupado: el subdominio va en la URL,
            # no es un secreto, y callarlo solo haría perder el tiempo.
            raise serializers.ValidationError(
                f'Ya existe un gimnasio con el subdominio "{subdominio}".',
            )
        return subdominio

    def validate_nombre_comercial(self, valor):
        nombre = valor.strip()
        if not nombre:
            raise serializers.ValidationError('El nombre no puede estar vacío.')
        return nombre

    def validate(self, datos):
        """Si no se indicó subdominio, se propone aquí para poder rechazar en
        validación (400) un nombre del que no sale ninguno válido -- por
        ejemplo, uno escrito solo con signos."""
        if datos.get('subdominio'):
            return datos
        try:
            datos['subdominio_propuesto'] = proponer_subdominio(datos['nombre_comercial'])
        except SubdominioInvalido as exc:
            raise serializers.ValidationError({
                'subdominio': (
                    f'{exc} Indica uno a mano para este nombre.'
                ),
            })
        return datos


class TenantConfiguracionSerializer(serializers.ModelSerializer):
    """Edición de la ficha de un gimnasio.

    Fuera de aquí, a propósito:

    * ``subdominio`` -- es la URL del cliente. Cambiarlo rompe sus enlaces
      guardados y expulsa a quien tenga la sesión abierta.
    * ``estado`` -- tiene su propia acción, porque suspender o cancelar
      arrastra consecuencias (deja fuera a todos sus usuarios, fija fechas de
      cancelación y purga) que no deben ocurrir de refilón al guardar un
      teléfono.
    * las fechas de alta, cancelación y purga -- las calcula el sistema.
    """

    class Meta:
        model = Tenant
        fields = (
            'nombre_comercial', 'responsable', 'correo', 'telefono', 'ciudad', 'nit',
            'logo_url', 'zona_horaria', 'moneda',
            'dias_aviso_vencimiento', 'minutos_antipassback',
        )

    def validate_zona_horaria(self, valor):
        return _validar_zona_horaria(valor)

    def validate_moneda(self, valor):
        moneda = valor.strip().upper()
        if len(moneda) != 3 or not moneda.isalpha():
            raise serializers.ValidationError('Usa el código ISO de 3 letras, por ejemplo "COP".')
        return moneda

    # Los rangos los impone también la base (`ck_tenants_dias_aviso`,
    # `ck_tenants_antipass`), pero un CHECK violado sale como IntegrityError
    # -> 500. Validarlos aquí los convierte en un 400 con un mensaje que se
    # puede leer.
    def validate_dias_aviso_vencimiento(self, valor):
        if not 0 <= valor <= 60:
            raise serializers.ValidationError('Debe estar entre 0 y 60 días.')
        return valor

    def validate_minutos_antipassback(self, valor):
        if not 0 <= valor <= 1440:
            raise serializers.ValidationError('Debe estar entre 0 y 1440 minutos (24 horas).')
        return valor


class CambioEstadoSerializer(serializers.Serializer):
    """Cambio del ciclo de vida de un gimnasio.

    ``confirmacion`` es el subdominio escrito a mano. No es burocracia:
    suspender o cancelar deja fuera a TODOS los usuarios de ese gimnasio de
    inmediato, y la lista del panel es una tabla de filas parecidas donde
    equivocarse de una es fácil.
    """

    estado = serializers.ChoiceField(choices=Tenant.EstadoTenant.choices)
    confirmacion = serializers.CharField()

    def validate(self, datos):
        tenant = self.context['tenant']
        if datos['confirmacion'].strip().lower() != tenant.subdominio.lower():
            raise serializers.ValidationError({
                'confirmacion': (
                    f'Escribe "{tenant.subdominio}" para confirmar el cambio.'
                ),
            })
        if datos['estado'] == tenant.estado:
            raise serializers.ValidationError({
                'estado': 'El gimnasio ya está en ese estado.',
            })
        return datos


