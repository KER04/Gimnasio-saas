import { Component, computed, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

/**
 * Pantalla mostrada cuando `permisoGuard` bloquea una ruta por falta de
 * permiso (Parte B del encargo de sesión/permisos). Evita dejar la pantalla
 * en blanco o generar un bucle de redirección hacia la propia ruta protegida.
 */
@Component({
  selector: 'app-sin-acceso',
  standalone: true,
  imports: [RouterLink],
  template: `
    <div class="sin-acceso">
      <h1>Sin acceso</h1>
      <p>
        Tu usuario no tiene el permiso
        @if (permiso(); as p) {
          <strong>"{{ p }}"</strong>
        } @else {
          necesario
        }
        para ver esta sección. Contacta a un administrador si crees que es un error.
      </p>
      <a routerLink="/">Volver al inicio</a>
    </div>
  `,
  styles: `
    .sin-acceso {
      display: flex;
      flex-direction: column;
      gap: 1rem;
      padding: 2rem;
      text-align: center;
    }
  `,
})
export class SinAcceso {
  private readonly route = inject(ActivatedRoute);

  protected readonly permiso = computed(() => this.route.snapshot.queryParamMap.get('permiso'));
}
