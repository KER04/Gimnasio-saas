import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { PlataformaService } from '../../../core/services/plataforma.service';

/**
 * Marco del panel del proveedor.
 *
 * No reutiliza `LayoutPrincipal`: aquel gira en torno a la sede activa, las
 * notificaciones y el buscador de clientes del gimnasio, nada de lo cual
 * existe aquí. Compartirlo obligaría a llenarlo de condicionales para
 * apagar la mitad de sus piezas.
 */
@Component({
  selector: 'app-layout-plataforma',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './layout-plataforma.html',
})
export class LayoutPlataforma {
  private readonly plataformaService = inject(PlataformaService);
  private readonly router = inject(Router);

  protected readonly usuario = this.plataformaService.usuario;

  constructor() {
    // Al recargar la página los tokens sobreviven en `localStorage` pero el
    // usuario no: sin esto la cabecera saldría vacía hasta el siguiente login.
    if (this.usuario() === null && this.plataformaService.estaAutenticado()) {
      this.plataformaService.cargarUsuario().subscribe({
        error: () => this.salir(),
      });
    }
  }

  protected iniciales(nombre: string): string {
    const partes = nombre.trim().split(/\s+/).filter(Boolean);
    if (partes.length === 0) {
      return '?';
    }
    return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase();
  }

  protected salir(): void {
    this.plataformaService.cerrarSesion();
    this.router.navigate(['/plataforma/login']);
  }
}
