/**
 * Extrae el subdominio del gimnasio a partir del hostname del navegador.
 *
 * En producción cada gimnasio entra por su propia URL
 * (`gimnasio1.miapp.com`), así que el subdominio identifica al tenant sin que
 * el usuario tenga que escribir nada. En desarrollo, entrando por `localhost`
 * a secas, no hay nada que deducir y hay que pedírselo.
 *
 * Función pura y sin dependencias de Angular: se puede probar sin navegador,
 * que importa porque Karma necesita Chrome y no siempre está disponible.
 */

/** `127.0.0.1` tiene cuatro segmentos separados por puntos igual que un
 * dominio, así que sin esto se interpretaría `127` como subdominio. */
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

export function subdominioDesdeHostname(hostname: string): string | null {
  if (!hostname) {
    return null;
  }

  // Defensivo: la firma espera un hostname, pero es fácil pasarle un `host`
  // (que incluye el puerto) sin darse cuenta.
  const limpio = hostname.split(':')[0].trim().toLowerCase();

  if (!limpio || limpio === 'localhost' || IPV4.test(limpio)) {
    return null;
  }

  const partes = limpio.split('.').filter((parte) => parte.length > 0);

  if (partes.length < 2) {
    return null;
  }

  // `gimx.localhost` -> `gimx`. Los navegadores resuelven cualquier
  // `*.localhost` a la máquina local, así que en desarrollo se puede
  // reproducir exactamente el comportamiento de producción sin tocar DNS.
  if (partes[partes.length - 1] === 'localhost') {
    return partes[0];
  }

  // A partir de aquí hacen falta TRES segmentos. Con dos estamos ante un
  // dominio desnudo (`miapp.com`), no ante un subdominio: devolver `miapp`
  // sería inventarse un gimnasio que no existe.
  if (partes.length < 3) {
    return null;
  }

  return partes[0];
}
