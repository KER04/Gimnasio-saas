"""Serializers de entrenamiento (RF-12): catálogo, rutinas y medidas."""
from rest_framework import serializers

from .models import (
    ControlMedida,
    Ejercicio,
    FichaMedidas,
    GrupoMuscular,
    Rutina,
    RutinaDia,
    RutinaEjercicio,
)

#: Las 13 medidas del formulario (decisión 8 del esquema). Se listan aquí y no
#: se escriben a mano en cada sitio para que añadir una el día de mañana sea
#: un cambio en un solo lugar.
MEDIDAS = (
    'peso_kg', 'cuello', 'hombros', 'pecho_espalda', 'brazos', 'antebrazos',
    'muneca', 'abdomen', 'cintura', 'cadera_gluteos', 'piernas_media',
    'rodillas_arriba', 'pantorrillas', 'tobillos',
)


class GrupoMuscularSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrupoMuscular
        fields = ('id', 'nombre', 'orden')
        read_only_fields = fields


class EjercicioSerializer(serializers.ModelSerializer):
    """Catálogo de ejercicios del gimnasio.

    Se da de baja, nunca se borra: ``RutinaEjercicio.ejercicio`` es
    ``PROTECT``, y aunque no lo fuera, borrar un ejercicio dejaría rutinas
    antiguas sin poder explicarse.
    """

    grupo_nombre = serializers.CharField(source='grupo_muscular.nombre', read_only=True)

    class Meta:
        model = Ejercicio
        fields = ('id', 'nombre', 'descripcion', 'grupo_muscular', 'grupo_nombre', 'activo')
        read_only_fields = ('id',)
        extra_kwargs = {'activo': {'required': False}}

    def validate_nombre(self, valor):
        nombre = valor.strip()
        if not nombre:
            raise serializers.ValidationError('El ejercicio necesita un nombre.')

        # `uq_ejercicios_nombre` es único por tenant; RLS ya acota la consulta.
        existentes = Ejercicio.objects.filter(nombre__iexact=nombre)
        if self.instance is not None:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise serializers.ValidationError('Ya existe un ejercicio con ese nombre.')
        return nombre


class RutinaEjercicioSerializer(serializers.ModelSerializer):
    """Un ejercicio dentro de un día de rutina, con lo que toca hacer.

    ``peso_kg`` es lo PLANIFICADO por el entrenador, no lo que el cliente
    levantó: eso vive en ``registros_ejercicios``, que no se gestiona todavía.
    """

    ejercicio_nombre = serializers.CharField(source='ejercicio.nombre', read_only=True)
    grupo_nombre = serializers.CharField(
        source='ejercicio.grupo_muscular.nombre', read_only=True,
    )

    class Meta:
        model = RutinaEjercicio
        fields = (
            'id', 'ejercicio', 'ejercicio_nombre', 'grupo_nombre', 'orden',
            'series', 'repeticiones', 'peso_kg', 'descanso_segundos', 'notas',
        )
        read_only_fields = ('id',)

    def validate_ejercicio(self, valor):
        if not valor.activo:
            raise serializers.ValidationError(
                'Ese ejercicio está dado de baja: no se puede añadir a una rutina nueva.',
            )
        return valor

    def validate(self, datos):
        # Réplica de `ck_rutejer_series` y `ck_rutejer_descanso`: sin esto, un
        # payload inválido llega a PostgreSQL y estalla como 500.
        for campo in ('series', 'repeticiones'):
            if campo in datos and datos[campo] <= 0:
                raise serializers.ValidationError({campo: 'Debe ser mayor que cero.'})
        descanso = datos.get('descanso_segundos')
        if descanso is not None and not 0 <= descanso <= 3600:
            raise serializers.ValidationError({
                'descanso_segundos': 'El descanso debe estar entre 0 y 3600 segundos (una hora).',
            })
        peso = datos.get('peso_kg')
        if peso is not None and peso < 0:
            raise serializers.ValidationError({'peso_kg': 'El peso no puede ser negativo.'})
        return datos


class RutinaDiaSerializer(serializers.ModelSerializer):
    ejercicios = RutinaEjercicioSerializer(many=True, required=False)

    class Meta:
        model = RutinaDia
        fields = ('id', 'numero', 'nombre', 'ejercicios')
        read_only_fields = ('id',)


class RutinaSerializer(serializers.ModelSerializer):
    """Rutina completa: se lee y se escribe ENTERA, con sus días y ejercicios.

    Es un documento, no una colección de filas sueltas: el entrenador la arma
    de una vez y la guarda de una vez. Endpoints separados para días y
    ejercicios obligarían al frontend a orquestar diez llamadas y a dejar la
    rutina a medias si una fallara.
    """

    dias = RutinaDiaSerializer(many=True, required=False)
    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    entrenador_nombre = serializers.CharField(source='entrenador.nombre', read_only=True)

    class Meta:
        model = Rutina
        fields = (
            'id', 'cliente', 'cliente_nombre', 'entrenador', 'entrenador_nombre',
            'nombre', 'objetivo', 'fecha_inicio', 'fecha_fin', 'activa', 'dias',
            'creado_en',
        )
        read_only_fields = ('id', 'entrenador', 'creado_en')
        extra_kwargs = {
            'fecha_inicio': {'required': False},
            'activa': {'required': False},
        }

    def validate(self, datos):
        inicio = datos.get('fecha_inicio') or getattr(self.instance, 'fecha_inicio', None)
        fin = datos.get('fecha_fin', getattr(self.instance, 'fecha_fin', None))
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError({
                'fecha_fin': 'La rutina no puede terminar antes de empezar.',
            })
        return datos

    def validate_dias(self, valor):
        numeros = [dia['numero'] for dia in valor]
        if len(numeros) != len(set(numeros)):
            raise serializers.ValidationError('Hay dos días con el mismo número.')
        for dia in valor:
            ordenes = [e['orden'] for e in dia.get('ejercicios', [])]
            if len(ordenes) != len(set(ordenes)):
                raise serializers.ValidationError(
                    f'En el día {dia["numero"]} hay dos ejercicios en la misma posición.',
                )
        return valor


class ControlMedidaSerializer(serializers.ModelSerializer):
    """Un control de medidas. Las 13 medidas son opcionales: en la práctica
    no siempre se toman todas, y exigirlas haría que no se registrara
    ninguna."""

    registrado_por_nombre = serializers.CharField(source='registrado_por.nombre', read_only=True)

    class Meta:
        model = ControlMedida
        fields = (
            'id', 'numero_control', 'fecha', 'edad', 'registrado_por',
            'registrado_por_nombre', 'creado_en', *MEDIDAS,
        )
        read_only_fields = ('id', 'numero_control', 'registrado_por', 'creado_en')
        extra_kwargs = {'fecha': {'required': False}}

    def validate_edad(self, valor):
        if valor is not None and not 5 <= valor <= 120:
            raise serializers.ValidationError('La edad debe estar entre 5 y 120 años.')
        return valor

    def validate(self, datos):
        for campo in MEDIDAS:
            valor = datos.get(campo)
            if valor is not None and valor <= 0:
                raise serializers.ValidationError({campo: 'Debe ser mayor que cero.'})
        return datos


class FichaMedidasSerializer(serializers.ModelSerializer):
    """Proceso de seguimiento corporal de un cliente.

    Solo puede haber UNA ficha activa por cliente a la vez: lo impone
    ``uq_ficha_cliente_activa`` en la base. Para empezar un proceso nuevo hay
    que cerrar el anterior, y así el histórico queda por etapas en vez de
    mezclado.
    """

    cliente_nombre = serializers.CharField(source='cliente.nombre', read_only=True)
    entrenador_nombre = serializers.CharField(source='entrenador.nombre', read_only=True)
    controles = ControlMedidaSerializer(many=True, read_only=True)

    class Meta:
        model = FichaMedidas
        fields = (
            'id', 'cliente', 'cliente_nombre', 'entrenador', 'entrenador_nombre',
            'modalidad', 'fecha_inicio', 'estatura_cm', 'whatsapp', 'activa',
            'controles', 'creado_en',
        )
        read_only_fields = ('id', 'entrenador', 'creado_en')
        extra_kwargs = {
            'fecha_inicio': {'required': False},
            'activa': {'required': False},
        }

    def validate_estatura_cm(self, valor):
        # `ck_ficha_estatura` exige entre 80 y 260 cm. El error más frecuente
        # es escribir metros (1,75) donde van centímetros.
        if valor is not None and not 80 <= valor <= 260:
            raise serializers.ValidationError(
                'La estatura va en CENTÍMETROS y debe estar entre 80 y 260.',
            )
        return valor

    def validate_cliente(self, valor):
        # RLS ya hace que un cliente de otro gimnasio no exista aquí.
        if self.instance is None and FichaMedidas.objects.filter(
            cliente=valor, activa=True,
        ).exists():
            raise serializers.ValidationError(
                'Ese cliente ya tiene un proceso de medidas abierto. Ciérralo antes '
                'de empezar otro.',
            )
        return valor
