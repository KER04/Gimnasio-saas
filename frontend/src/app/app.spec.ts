import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      // App solo contiene un <router-outlet>, que necesita el router provisto
      // para poder instanciarse en pruebas.
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('se crea correctamente', () => {
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('es solo el contenedor de rutas: monta un router-outlet', () => {
    // El marco de la aplicación (cabecera, menú lateral, pie) ya no vive aquí
    // sino en LayoutPrincipal, porque el login tiene que renderizarse fuera de
    // él. App quedó reducido a decidir qué ruta se pinta.
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const elemento = fixture.nativeElement as HTMLElement;
    expect(elemento.querySelector('router-outlet')).not.toBeNull();
  });
});
