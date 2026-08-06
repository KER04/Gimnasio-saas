import { subdominioDesdeHostname } from './subdominio.util';

describe('subdominioDesdeHostname', () => {
  it('extrae el subdominio de un dominio de producción', () => {
    expect(subdominioDesdeHostname('gimnasio1.miapp.com')).toBe('gimnasio1');
    expect(subdominioDesdeHostname('powerfit.miapp.com')).toBe('powerfit');
  });

  it('soporta *.localhost, que es como se reproduce producción en local', () => {
    expect(subdominioDesdeHostname('gimx.localhost')).toBe('gimx');
  });

  it('devuelve null cuando no hay gimnasio que deducir', () => {
    expect(subdominioDesdeHostname('localhost')).toBeNull();
    expect(subdominioDesdeHostname('127.0.0.1')).toBeNull();
    expect(subdominioDesdeHostname('192.168.1.50')).toBeNull();
    expect(subdominioDesdeHostname('')).toBeNull();
  });

  it('NO confunde un dominio desnudo con un subdominio', () => {
    // El caso sutil: `miapp.com` tiene dos segmentos igual que
    // `gimx.localhost`, pero aquí `miapp` es el dominio, no un gimnasio.
    expect(subdominioDesdeHostname('miapp.com')).toBeNull();
  });

  it('normaliza mayúsculas y tolera que le pasen el puerto', () => {
    expect(subdominioDesdeHostname('GIMX.MIAPP.COM')).toBe('gimx');
    expect(subdominioDesdeHostname('gimx.miapp.com:4200')).toBe('gimx');
  });

  it('con subdominios anidados devuelve el primero', () => {
    expect(subdominioDesdeHostname('a.b.miapp.com')).toBe('a');
  });

  it('NO toma el dominio que asigna el PaaS como si fuera un gimnasio', () => {
    // El fallo que esto evita: sin la excepción, el login daba por deducido
    // un gimnasio llamado `frontend-production-11c4`, escondía el campo
    // "código de gimnasio" y dejaba a todo el mundo fuera.
    expect(subdominioDesdeHostname('frontend-production-11c4.up.railway.app')).toBeNull();
    expect(subdominioDesdeHostname('mi-app.vercel.app')).toBeNull();
    expect(subdominioDesdeHostname('mi-app.netlify.app')).toBeNull();
    expect(subdominioDesdeHostname('mi-app.onrender.com')).toBeNull();
  });

  it('el sufijo del PaaS se compara como dominio, no como texto final', () => {
    // `mivercel.app` acaba en "vercel.app" si se compara como cadena suelta,
    // pero es un dominio propio: ahí `gimx` SÍ es un gimnasio.
    expect(subdominioDesdeHostname('gimx.mivercel.app')).toBe('gimx');
  });

  it('sigue deduciendo el gimnasio con dominio propio', () => {
    // El día que haya dominio con comodín, esto es lo que tiene que pasar.
    expect(subdominioDesdeHostname('gimx.midominio.com')).toBe('gimx');
  });
});
