from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

Usuario = get_user_model()


class UsuarioSerializer(serializers.ModelSerializer):
    """Serializer de lectura del usuario autenticado.

    ``tenant_id`` se declara explícitamente porque no es un campo de
    modelo "de verdad" (es el atributo que Django genera para la columna
    de la FK ``tenant``): ModelSerializer no lo detecta automáticamente a
    partir de sólo el nombre en ``Meta.fields``.
    """

    tenant_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Usuario
        fields = ('id', 'correo', 'nombre', 'rol', 'tenant_id', 'activo', 'creado_en')
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer de registro. El tenant NUNCA se toma directamente de este
    serializer: lo resuelve la vista (``RegisterView``, ver Parte A2 del
    encargo de "campo subdominio explícito") combinando, en este orden, el
    campo ``subdominio`` del cuerpo (si viene) y ``request.tenant``
    (subdominio del Host/JWT/sesión, publicado por ``TenantMiddleware``), y
    se inyecta en ``create()`` vía ``request.tenant``. ``subdominio`` aquí
    solo sirve para que DRF no descarte el campo silenciosamente ni se queje
    de un campo "no esperado"; no participa en ``create()``. ``rol`` sí es
    un campo de entrada (id de un rol del propio tenant): al validarse
    mientras la petición ya está dentro de ``tenant_context`` (ver
    ``RegisterView``), RLS hace que un id de rol de OTRO tenant sencillamente
    no exista para esta consulta -- no hace falta una validación cruzada
    adicional, la base de datos ya la impone.
    """

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
    )
    correo = serializers.EmailField(required=True)
    # write_only=True es obligatorio aquí: no es un campo del modelo Usuario,
    # así que si no fuera write_only, `serializer.data` (usado en
    # RegisterView para las cabeceras de éxito) intentaría leer
    # `usuario.subdominio` y reventaría con AttributeError.
    subdominio = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Usuario
        fields = ('correo', 'nombre', 'password', 'rol', 'telefono', 'subdominio')

    def validate_correo(self, value):
        tenant = self.context['request'].tenant
        # Consulta dentro de tenant_context (abierto por la vista): RLS ya
        # acota a este tenant, pero se compara también tenant= explícito
        # por claridad y para no depender únicamente del contexto implícito.
        if Usuario.objects.filter(correo__iexact=value, tenant=tenant).exists():
            raise serializers.ValidationError(
                'Ya existe un usuario registrado con este correo en este gimnasio.'
            )
        return value

    def create(self, validated_data):
        tenant = self.context['request'].tenant
        return Usuario.objects.create_user(
            correo=validated_data['correo'],
            nombre=validated_data['nombre'],
            tenant=tenant,
            rol=validated_data['rol'],
            password=validated_data['password'],
            telefono=validated_data.get('telefono'),
        )


class LoginSerializer(TokenObtainPairSerializer):
    """Serializer de login (Parte C1; campo ``subdominio`` explícito
    añadido después, ver encargo "el API debe poder recibir el gimnasio en
    el cuerpo").

    El campo de identificación es ``correo`` y no ``username`` sin necesidad
    de declararlo a mano: ``TokenObtainSerializer.username_field`` se calcula
    como ``get_user_model().USERNAME_FIELD``, que ya es ``'correo'`` (Parte
    A). ``authenticate()`` (llamado por la clase base) delega en
    ``TenantAuthBackend`` (Parte B), que exige un tenant resuelto -- aquí
    viene de ``request.tenant_id``, que ``LoginView.post`` fija ANTES de
    llamar a ``super().post()`` (por tanto antes de que se ejecute esta
    validación), combinando el ``subdominio`` del cuerpo con el que ya haya
    resuelto ``TenantMiddleware`` por Host/JWT/sesión.

    ``subdominio`` NO es una credencial: solo le dice a la vista en qué
    tenant buscar al usuario. Por eso se declara aquí (para que DRF lo
    acepte como campo de entrada válido y aparezca en la documentación de la
    API) pero la propia resolución del tenant vive en ``LoginView.post``, no
    en ``validate()`` -- tiene que ocurrir ANTES de que ``authenticate()``
    (dentro de ``validate()``) necesite ``request.tenant_id`` ya fijado.
    """

    subdominio = serializers.CharField(required=False, allow_blank=True, write_only=True)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Claim de la Parte C: el tenant viaja DENTRO del token, para que
        # TenantMiddleware pueda resolverlo en cada petición posterior sin
        # depender del subdominio. RefreshToken.access_token copia este
        # claim al access token derivado, así que basta con fijarlo aquí.
        token['tenant_id'] = user.tenant_id
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UsuarioSerializer(self.user).data
        return data
