/**
 * Resolución de tenant a partir del `hostname` del navegador, en el
 * frontend (contraparte de `_subdominio_desde_host` en
 * `apps/core/middleware.py` del backend).
 *
 * Existe porque el login/register ya no dependen EXCLUSIVAMENTE del Host
 * que ve el backend: si Angular se sirve en `gimx.tuapp.com` pero el API
 * vive en `api.tuapp.com`, el backend nunca ve el subdominio del gimnasio
 * en el `Host` de la petición. `AuthService` usa esta función para rellenar
 * el campo `subdominio` del cuerpo de login/register con lo que el propio
 * navegador sí conoce: la URL en la que el usuario está parado.
 */

/** IPv4 literal (`127.0.0.1`, `10.0.0.5`, ...): nunca tiene subdominio de tenant. */
const IPV4_REGEX = /^\d{1,3}(\.\d{1,3}){3}$/;

/**
 * Extrae el subdominio (tenant) de un `hostname`, o `null` si no aplica.
 *
 * Casos cubiertos:
 * - `'gimx.tuapp.com'` -> `'gimx'` (producción: subdominio.dominio.tld).
 * - `'gimx.localhost'` -> `'gimx'` (desarrollo local: los navegadores
 *   resuelven cualquier `*.localhost` a 127.0.0.1 sin tocar `/etc/hosts` ni
 *   DNS -- `localhost` no es un TLD real, así que 2 segmentos ya bastan
 *   para tratar el primero como subdominio).
 * - `'localhost'`, `'127.0.0.1'`, `'tuapp.com'` -> `null` (host "desnudo",
 *   sin subdominio de tenant; un dominio de producción de 2 segmentos NO
 *   se confunde con un subdominio real -- para eso se exigen 3+ segmentos
 *   fuera del caso especial `*.localhost`).
 *
 * Pura y defensiva: se espera recibir solo el hostname (sin protocolo, sin
 * puerto, sin path -- lo que da `window.location.hostname`), pero por si
 * acaso llega con puerto (`'gimx.localhost:4200'`) o en mayúsculas, los
 * normaliza de todas formas antes de analizarlo.
 */
export function subdominioDesdeHostname(hostname: string): string | null {
  if (!hostname) {
    return null;
  }

  // Defensivo: si por error llegara con puerto, se descarta (se ignora el
  // puerto, como pide el encargo). window.location.hostname normal ya NO
  // trae puerto, pero no cuesta nada ser tolerante.
  const sinPuerto = hostname.split(':')[0].trim().toLowerCase();

  if (!sinPuerto || sinPuerto === 'localhost' || IPV4_REGEX.test(sinPuerto)) {
    return null;
  }

  const partes = sinPuerto.split('.').filter((parte) => parte.length > 0);

  if (partes.length < 2) {
    return null;
  }

  // Caso especial de desarrollo: cualquier `*.localhost` -- 'localhost' no
  // es un TLD real, así que no hace falta un tercer segmento para que el
  // primero sea un subdominio genuino.
  if (partes[partes.length - 1] === 'localhost') {
    return partes[0];
  }

  // Producción: se exige subdominio.dominio.tld (3+ segmentos). Un host de
  // solo 2 segmentos (p. ej. 'tuapp.com') es el dominio "desnudo", sin
  // subdominio -- devolver 'tuapp' ahí sería inventar un tenant que no
  // existe.
  if (partes.length < 3) {
    return null;
  }

  return partes[0];
}
