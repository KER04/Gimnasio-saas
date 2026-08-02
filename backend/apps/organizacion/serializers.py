"""Serializers de la API de organización (Parte C del encargo de
membresías: ``/api/sedes/``)."""
from rest_framework import serializers

from .models import Sede


class SedeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sede
        fields = ('id', 'nombre', 'direccion', 'telefono', 'activa')
        read_only_fields = fields
