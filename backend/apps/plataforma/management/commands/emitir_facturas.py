"""Emite las facturas de suscripción que ya tocan y actualiza las moras.

    python manage.py emitir_facturas --simular   # ver qué haría, sin tocar nada
    python manage.py emitir_facturas

Pensado para lanzarlo a mano una vez al mes, o desde un cron del proveedor de
hosting. No corre solo: ver el docstring de ``apps.plataforma.facturacion``
sobre por qué conviene que haya una persona en el camino.

La lógica de qué se cobra vive entera en ``facturacion``; aquí solo se
recorre la lista y se cuenta lo que pasó.
"""
from datetime import date

from django.core.management.base import BaseCommand

from apps.plataforma.facturacion import FacturacionError, emitir_factura, marcar_mora
from apps.plataforma.models import Suscripcion

#: Tope de facturas por gimnasio y pasada. Con ciclo mensual son dos años de
#: atrasos: más que eso no es un cliente moroso, es un dato mal puesto.
_MAX_PERIODOS_POR_PASADA = 24


class Command(BaseCommand):
    help = (
        'Emite las facturas de suscripción cuyo corte ya venció y marca en '
        'mora a quien tenga facturas pasadas de su plazo de gracia.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--simular',
            action='store_true',
            help='Enseña qué se emitiría, sin escribir nada en la base de datos.',
        )
        parser.add_argument(
            '--fecha',
            help=(
                'Fecha de referencia en formato AAAA-MM-DD (por defecto, hoy). '
                'Útil para reproducir un cierre pasado.'
            ),
        )

    def handle(self, *args, **options):
        hoy = date.fromisoformat(options['fecha']) if options.get('fecha') else date.today()
        simular = options['simular']

        if simular:
            self.stdout.write(self.style.WARNING('MODO SIMULACIÓN: no se escribe nada.\n'))

        suscripciones = (
            Suscripcion.objects
            .exclude(estado=Suscripcion.EstadoSuscripcion.CANCELADA)
            .select_related('tenant', 'plan_suscripcion')
            .order_by('proximo_corte')
        )

        emitidas = 0
        omitidas = 0
        en_mora = 0

        for suscripcion in suscripciones:
            nombre = suscripcion.tenant.nombre_comercial

            # Se factura hasta ponerse al día, no un periodo por pasada. Un
            # gimnasio que lleva tres meses sin facturar debe tres meses: si
            # cada ejecución emitiera solo uno, la deuda real quedaría
            # escondida y se cobraría de menos sin que nadie lo notara.
            #
            # El tope existe para que un `proximo_corte` corrupto (una fecha
            # de 1970, por ejemplo) no genere miles de facturas: si se
            # alcanza, es un dato malo y hay que mirarlo, no seguir emitiendo.
            for _ in range(_MAX_PERIODOS_POR_PASADA):
                if suscripcion.proximo_corte > hoy:
                    break

                if simular:
                    self.stdout.write(
                        f'  emitiría  {nombre}: periodo desde '
                        f'{suscripcion.proximo_corte:%d/%m/%Y} '
                        f'({suscripcion.plan_suscripcion.nombre})'
                    )
                    emitidas += 1
                    # En simulación no se avanza el corte (no se escribe
                    # nada), así que se para tras enseñar el primero.
                    break

                try:
                    factura = emitir_factura(suscripcion, hoy=hoy)
                except FacturacionError as exc:
                    # Un gimnasio sin sedes activas no debe detener el cierre
                    # de los demás: se anota y se sigue con el siguiente.
                    self.stdout.write(self.style.WARNING(f'  omitido   {nombre}: {exc}'))
                    omitidas += 1
                    break

                emitidas += 1
                self.stdout.write(
                    f'  emitida   {nombre}: {factura.monto} '
                    f'({factura.sedes_facturadas} sede(s), periodo '
                    f'{factura.periodo_inicio:%d/%m/%Y} - {factura.periodo_fin:%d/%m/%Y})'
                )
            else:
                self.stdout.write(self.style.ERROR(
                    f'  ATENCIÓN  {nombre}: se alcanzó el tope de '
                    f'{_MAX_PERIODOS_POR_PASADA} periodos en una pasada. '
                    'Revisa su próximo corte antes de volver a ejecutar.'
                ))

        if not simular:
            for suscripcion in suscripciones:
                if marcar_mora(suscripcion, hoy=hoy):
                    if suscripcion.estado == Suscripcion.EstadoSuscripcion.MORA:
                        en_mora += 1
                        self.stdout.write(self.style.WARNING(
                            f'  en mora   {suscripcion.tenant.nombre_comercial}'
                        ))
                    else:
                        self.stdout.write(self.style.SUCCESS(
                            f'  al día    {suscripcion.tenant.nombre_comercial}'
                        ))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'{emitidas} factura(s) {"a emitir" if simular else "emitidas"}, '
            f'{omitidas} omitida(s), {en_mora} gimnasio(s) marcado(s) en mora.'
        ))
        if en_mora:
            self.stdout.write(
                'Marcar en mora NO suspende a nadie: el gimnasio sigue '
                'funcionando. Suspender se decide a mano desde el panel.'
            )
