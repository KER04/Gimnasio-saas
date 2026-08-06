"""Serializers de la API de organización: sedes, roles y usuarios."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from .models import Rol, Sede, UsuarioSede

Usuario = get_user_model()

#: Permiso que define a un "administrador" a efectos de no dejar al gimnasio
#: sin nadie que pueda administrarlo. Se mira el PERMISO y no el nombre del
#: rol: los roles son configurables y llamarse "administrador" no garantiza
#: nada, mientras que tener `config.usuarios` sí es exactamente la capacidad
#: que no puede desaparecer.
PERMISO_ADMINISTRAR_USUARIOS = 'config.usuarios'


def hay_otro_administrador(usuario):
    """``True`` si el gimnasio tiene OTRO usuario activo capaz de administrar
    usuarios, aparte del que se pasa.

    Es la comprobación que evita el peor accidente de esta pantalla: quedarse
    sin ningún administrador. Si eso pasa, nadie dentro del gimnasio puede
    crear usuarios, cambiar roles ni restablecer contraseñas -- la única
    salida sería llamar al proveedor.
    """
    return (
        Usuario.objects
        .filter(
            tenant_id=usuario.tenant_id,
            activo=True,
            rol__roles_permisos__permiso__codigo=PERMISO_ADMINISTRAR_USUARIOS,
        )
        .exclude(pk=usuario.pk)
        .exists()
    )


class SedeSerializer(serializers.ModelSerializer):
    """Lectura de una sede, para el selector de sede de toda la aplicación."""

    class Meta:
        model = Sede
        fields = ('id', 'nombre', 'direccion', 'telefono', 'activa')
        read_only_fields = fields


class SedeAdminSerializer(serializers.ModelSerializer):
    """Escritura de sedes (``config.sedes``).

    ``prefijo_comprobante`` sí es editable, pero solo tiene efecto en los
    recibos que se emitan A PARTIR de ahora: el consecutivo ya asignado a
    una venta no se recalcula. Cambiarlo con ventas hechas deja el histórico
    con dos prefijos distintos, que es lo correcto (el recibo dice lo que
    decía cuando se emitió) pero conviene saberlo.
    """

    class Meta:
        model = Sede
        fields = (
            'id', 'nombre', 'direccion', 'telefono', 'nit',
            'encabezado_recibo', 'prefijo_comprobante', 'activa',
        )
        read_only_fields = ('id',)
        extra_kwargs = {
            'nombre': {'required': True},
            'direccion': {'required': True},
            # `db_default` en el modelo: lo pone PostgreSQL, y DRF solo mira
            # `default=`, así que sin esto los daría por obligatorios.
            'prefijo_comprobante': {'required': False},
            'activa': {'required': False},
        }

    def validate_nombre(self, valor):
        nombre = valor.strip()
        if not nombre:
            raise serializers.ValidationError('La sede necesita un nombre.')

        # `uq_sedes_nombre` es único por tenant. RLS ya acota la consulta al
        # gimnasio actual, así que basta con excluirse a uno mismo al editar.
        existentes = Sede.objects.filter(nombre__iexact=nombre)
        if self.instance is not None:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise serializers.ValidationError('Ya hay una sede con ese nombre.')
        return nombre

    def validate_prefijo_comprobante(self, valor):
        prefijo = valor.strip().upper()
        if not prefijo:
            raise serializers.ValidationError('El prefijo no puede estar vacío.')
        if not prefijo.isalnum():
            raise serializers.ValidationError('Usa solo letras y números, sin espacios ni signos.')
        return prefijo


class RolSerializer(serializers.ModelSerializer):
    """Los roles del gimnasio. Solo lectura: hoy se usan los cuatro sembrados
    al crear el tenant (``es_sistema=True``). El modelo admite roles a medida
    (``RolPermiso`` es una N:M abierta), pero eso necesita un editor de
    permisos y se decidió dejarlo para más adelante."""

    permisos = serializers.SerializerMethodField()

    class Meta:
        model = Rol
        fields = ('id', 'nombre', 'descripcion', 'es_sistema', 'activo', 'permisos')
        read_only_fields = fields

    def get_permisos(self, obj):
        return sorted(rp.permiso_id for rp in obj.roles_permisos.all())


class UsuarioSerializer(serializers.ModelSerializer):
    """Lectura de un usuario del gimnasio.

    NUNCA expone ``password``: el campo existe en el modelo como hash y no
    tiene por qué salir de la base de datos.
    """

    rol_nombre = serializers.CharField(source='rol.nombre', read_only=True)
    sedes = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = (
            'id', 'nombre', 'correo', 'telefono', 'rol', 'rol_nombre',
            'activo', 'sedes', 'last_login', 'creado_en',
        )
        read_only_fields = fields

    def get_sedes(self, obj):
        return [
            {'id': us.sede_id, 'nombre': us.sede.nombre}
            for us in obj.usuarios_sedes.all()
        ]


class UsuarioCrearSerializer(serializers.ModelSerializer):
    """Alta de un empleado.

    La contraseña NO se pide: la genera el servidor y se devuelve una sola
    vez, igual que al dar de alta un gimnasio desde el panel del proveedor.
    Así el comportamiento es el mismo en todo el producto y nadie teclea
    "123456" por comodidad.
    """

    sedes = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Sede.objects.all(), required=False,
    )

    class Meta:
        model = Usuario
        fields = ('nombre', 'correo', 'telefono', 'rol', 'sedes')
        extra_kwargs = {
            'nombre': {'required': True},
            'correo': {'required': True},
            'rol': {'required': True},
        }

    def validate_correo(self, valor):
        """Único DENTRO del gimnasio: la misma persona puede trabajar en dos
        gimnasios clientes distintos. RLS ya acota esta consulta al tenant
        actual, así que no hace falta filtrar por él a mano."""
        correo = valor.strip().lower()
        if Usuario.objects.filter(correo__iexact=correo).exists():
            raise serializers.ValidationError('Ya hay un usuario con ese correo en este gimnasio.')
        return correo

    def validate_rol(self, valor):
        # RLS hace que un rol de otro gimnasio sencillamente no exista para
        # esta consulta, así que llegar aquí ya implica que es del tenant.
        if not valor.activo:
            raise serializers.ValidationError('Ese rol está dado de baja.')
        return valor


class UsuarioActualizarSerializer(serializers.ModelSerializer):
    """Edición de un empleado.

    El ``correo`` no se edita: es la credencial con la que entra y cambiarlo
    desde otra sesión equivale a apropiarse de la cuenta. Tampoco ``activo``,
    que tiene sus propias acciones porque arrastra comprobaciones.
    """

    sedes = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Sede.objects.all(), required=False,
    )

    class Meta:
        model = Usuario
        fields = ('nombre', 'telefono', 'rol', 'sedes')

    def validate_rol(self, valor):
        if not valor.activo:
            raise serializers.ValidationError('Ese rol está dado de baja.')

        usuario = self.instance
        peticionario = self.context['request'].user

        if usuario.pk == peticionario.pk and valor.pk != usuario.rol_id:
            # Cambiarse el rol a uno mismo es la forma más rápida de perder
            # los permisos con los que estabas administrando, sin manera de
            # recuperarlos.
            raise serializers.ValidationError(
                'No puedes cambiar tu propio rol. Pídeselo a otro administrador.',
            )

        if valor.pk != usuario.rol_id and self._pierde_administracion(usuario, valor):
            raise serializers.ValidationError(
                'Es el único administrador activo del gimnasio. Si le cambias el rol, '
                'nadie podrá gestionar usuarios ni restablecer contraseñas.',
            )
        return valor

    @staticmethod
    def _pierde_administracion(usuario, rol_nuevo):
        """``True`` si el cambio dejaría al gimnasio sin administradores."""
        era_admin = usuario.rol.roles_permisos.filter(
            permiso__codigo=PERMISO_ADMINISTRAR_USUARIOS,
        ).exists()
        if not era_admin:
            return False
        sigue_siendo = rol_nuevo.roles_permisos.filter(
            permiso__codigo=PERMISO_ADMINISTRAR_USUARIOS,
        ).exists()
        return not sigue_siendo and not hay_otro_administrador(usuario)
