/**
 * Configuración de PRODUCCIÓN.
 *
 * `apiUrl` es relativa a propósito: el tenant no viaja en la URL del API sino
 * dentro del JWT (y como campo `subdominio` en el login, que es la única
 * petición que aún no tiene token). Si algún día el API vive en otro host
 * —`api.miapp.com` sirviendo a `gimnasio1.miapp.com`—, basta con poner aquí
 * la URL absoluta: nada más cambia, porque el gimnasio nunca se dedujo del
 * host del API.
 */
export const environment = {
  production: true,
  apiUrl: 'https://gimnasio-saas-production.up.railway.app/api',
};
