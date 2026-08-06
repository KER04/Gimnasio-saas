import { AbstractControl, ValidationErrors } from '@angular/forms';

/**
 * Importes de dinero, manejados SIEMPRE como cadena y nunca como `number`
 * (mismo criterio que documenta `plan.model.ts` para `Plan.precio`): así el
 * valor que se guarda y el que se muestra son exactamente el que se tecleó,
 * sin redondeos de coma flotante.
 *
 * Corolario importante para las plantillas: los campos de importe se pintan
 * con `type="text"` + `inputmode="decimal"`, NUNCA con `type="number"`. En un
 * campo numérico la rueda del ratón y las flechas del teclado modifican el
 * valor en silencio -- basta pasar el ratón por encima y hacer scroll para
 * que un 5000 recién tecleado acabe siendo 4998 sin que el usuario toque nada.
 */

/**
 * Convierte lo que el usuario escribe en el importe canónico que espera el
 * backend (`"5000"` / `"4998.50"`), o `null` si no es un importe válido.
 *
 * Convenio es-CO: `,` separa decimales y `.` separa miles. Un `.` seguido de
 * solo 1-2 dígitos no puede ser separador de miles (que agrupa de 3 en 3),
 * así que se acepta como decimal escrito a la inglesa; `.` seguido de 3
 * dígitos es siempre separador de miles ("5.000" son cinco mil pesos).
 */
export function normalizarPrecio(texto: string): string | null {
  const limpio = texto.replace(/[\s$ ]/g, '');
  if (limpio === '' || !/^[\d.,]+$/.test(limpio)) {
    return null;
  }

  let entero: string;
  let decimales = '';

  if (limpio.includes(',')) {
    const partes = limpio.split(',');
    if (partes.length !== 2 || !/^\d{1,2}$/.test(partes[1])) {
      return null;
    }
    entero = partes[0].replace(/\./g, '');
    decimales = partes[1];
  } else {
    const partes = limpio.split('.');
    if (partes.length === 1) {
      entero = partes[0];
    } else if (partes.length === 2 && /^\d{1,2}$/.test(partes[1])) {
      entero = partes[0];
      decimales = partes[1];
    } else {
      if (!partes.slice(1).every((grupo) => /^\d{3}$/.test(grupo))) {
        return null;
      }
      entero = partes.join('');
    }
  }

  if (!/^\d+$/.test(entero)) {
    return null;
  }
  // `max_digits=12` en el modelo: 10 enteros + 2 decimales.
  const sinCerosIzquierda = entero.replace(/^0+(?=\d)/, '');
  if (sinCerosIzquierda.length > 10) {
    return null;
  }

  return decimales === '' ? sinCerosIzquierda : `${sinCerosIzquierda}.${decimales.padEnd(2, '0')}`;
}

/**
 * Formatea un importe canónico para mostrarlo, operando sobre la CADENA: no
 * pasa por `Number`, así que el valor que se ve es exactamente el guardado,
 * sin redondeos. Los centavos solo aparecen si no son cero.
 */
export function formatearMonto(valor: string): string {
  const [entero, decimales = ''] = valor.split('.');
  const conMiles = (entero || '0').replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const centavos = decimales.padEnd(2, '0').slice(0, 2);
  return centavos === '00' ? conMiles : `${conMiles},${centavos}`;
}

/** Importe canónico ya formateado y con símbolo, listo para pintar. */
export function precioParaMostrar(valor: string): string {
  return `$ ${formatearMonto(valor)}`;
}

/** Rechaza importes que `normalizarPrecio` no sabe interpretar. El campo
 * vacío lo cubre `Validators.required`, no este validador. */
export function precioValido(control: AbstractControl): ValidationErrors | null {
  const texto = String(control.value ?? '').trim();
  if (texto === '') {
    return null;
  }
  return normalizarPrecio(texto) === null ? { precioInvalido: true } : null;
}
