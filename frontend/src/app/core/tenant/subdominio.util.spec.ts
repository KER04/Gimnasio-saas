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
});
