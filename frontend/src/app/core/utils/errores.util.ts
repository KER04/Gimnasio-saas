/**
 * Aplana los errores de validación de DRF a mensajes legibles.
 *
 * DRF devuelve una estructura que refleja la forma del cuerpo enviado. Con
 * datos anidados —una rutina con sus días y sus ejercicios— eso son tres
 * niveles:
 *
 * ```json
 * { "dias": [ { "ejercicios": [ { "series": ["Debe ser mayor que cero."] } ] } ] }
 * ```
 *
 * Mostrar eso con `String(valor)` acaba en `[object Object]`, que es
 * exactamente lo que veía el usuario: sabía que algo estaba mal, pero no qué
 * ni dónde. Aquí sale "Día 1 · Ejercicio 2: Debe ser mayor que cero".
 */

/** Listas cuyo índice significa algo para quien lee. */
const LISTAS_NUMERADAS: Record<string, string> = {
  dias: 'Día',
  ejercicios: 'Ejercicio',
  controles: 'Control',
};

/** Campos cuyo nombre técnico no se entiende tal cual. */
const NOMBRES_DE_CAMPO: Record<string, string> = {
  series: 'series',
  repeticiones: 'repeticiones',
  peso_kg: 'peso',
  descanso_segundos: 'descanso',
  duracion_minutos: 'duración',
  fecha_fin: 'fecha de fin',
  fecha_inicio: 'fecha de inicio',
  estatura_cm: 'estatura',
  grupo_muscular: 'grupo muscular',
  categoria_gasto: 'categoría',
  categoria_ingreso: 'categoría',
};

function unir(contexto: string[], mensaje: string): string {
  return contexto.length > 0 ? `${contexto.join(' · ')}: ${mensaje}` : mensaje;
}

export function mensajesDeError(cuerpo: unknown, contexto: string[] = []): string[] {
  if (typeof cuerpo === 'string') {
    return [unir(contexto, cuerpo)];
  }

  // Una lista suelta de cadenas son varios errores del MISMO campo, no
  // posiciones distintas: no se numeran.
  if (Array.isArray(cuerpo)) {
    return cuerpo.flatMap((elemento) => mensajesDeError(elemento, contexto));
  }

  if (cuerpo === null || typeof cuerpo !== 'object') {
    return [];
  }

  return Object.entries(cuerpo as Record<string, unknown>).flatMap(([clave, valor]) => {
    // Mensajes generales: nombrarlos en el texto solo añadiría ruido.
    if (clave === 'detail' || clave === 'non_field_errors') {
      return mensajesDeError(valor, contexto);
    }

    const etiquetaLista = LISTAS_NUMERADAS[clave];
    if (etiquetaLista && Array.isArray(valor)) {
      return valor.flatMap((elemento, indice) => {
        // Un elemento sin errores viene como objeto vacío: se salta para no
        // numerar hacia adelante días que están bien.
        if (mensajesDeError(elemento).length === 0) {
          return [];
        }
        // Se cuenta desde 1: quien lee "Día 2" mira el segundo de la
        // pantalla, no el tercero.
        return mensajesDeError(elemento, [...contexto, `${etiquetaLista} ${indice + 1}`]);
      });
    }

    return mensajesDeError(valor, [...contexto, NOMBRES_DE_CAMPO[clave] ?? clave]);
  });
}

/** El primer mensaje, o `null` si no hay ninguno. Para cuando solo cabe uno. */
export function primerMensajeDeError(cuerpo: unknown): string | null {
  return mensajesDeError(cuerpo)[0] ?? null;
}
