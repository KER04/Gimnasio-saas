import { subdominioDesdeHostname } from './subdominio.util';

describe('subdominioDesdeHostname', () => {
  it('extrae el subdominio de un host de producción (subdominio.dominio.tld)', () => {
    expect(subdominioDesdeHostname('gimx.tuapp.com')).toBe('gimx');
  });

  it('extrae el subdominio de un host *.localhost de desarrollo', () => {
    expect(subdominioDesdeHostname('gimx.localhost')).toBe('gimx');
  });

  it('devuelve null para "localhost" a secas', () => {
    expect(subdominioDesdeHostname('localhost')).toBeNull();
  });

  it('devuelve null para "127.0.0.1"', () => {
    expect(subdominioDesdeHostname('127.0.0.1')).toBeNull();
  });

  it('devuelve null para un dominio "desnudo" de 2 segmentos (sin subdominio)', () => {
    expect(subdominioDesdeHostname('tuapp.com')).toBeNull();
  });

  it('ignora el puerto si llegara incluido por error', () => {
    expect(subdominioDesdeHostname('gimx.localhost:4200')).toBe('gimx');
    expect(subdominioDesdeHostname('gimx.tuapp.com:443')).toBe('gimx');
  });

  it('es insensible a mayúsculas', () => {
    expect(subdominioDesdeHostname('GIMX.TUAPP.COM')).toBe('gimx');
  });

  it('devuelve null para una cadena vacía', () => {
    expect(subdominioDesdeHostname('')).toBeNull();
  });

  it('devuelve null para otra IPv4 cualquiera', () => {
    expect(subdominioDesdeHostname('10.0.0.5')).toBeNull();
  });

  it('soporta un tercer nivel de subdominio, quedándose con el primer segmento', () => {
    expect(subdominioDesdeHostname('gimx.staging.tuapp.com')).toBe('gimx');
  });
});
