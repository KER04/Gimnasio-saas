import { Pipe, PipeTransform } from '@angular/core';

/**
 * Formatea un monto como pesos colombianos: sin decimales y con separador de
 * miles (p. ej. `$50.000`). El requisito (RF-06/RF-23) es explícito en que
 * el COP no se maneja con decimales, así que no se reutiliza el pipe
 * `currency` estándar de Angular con `digitsInfo` variable en cada plantilla:
 * se centraliza aquí una única vez el formato exacto que pide el negocio.
 */
@Pipe({
  name: 'cop',
  standalone: true,
})
export class CopCurrencyPipe implements PipeTransform {
  private readonly formateador = new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

  transform(valor: number | string | null | undefined): string {
    if (valor === null || valor === undefined || valor === '') {
      return this.formateador.format(0);
    }
    const numero = typeof valor === 'string' ? Number(valor) : valor;
    if (Number.isNaN(numero)) {
      return this.formateador.format(0);
    }
    return this.formateador.format(numero);
  }
}
