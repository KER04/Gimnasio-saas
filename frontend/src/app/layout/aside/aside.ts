import { Component, HostListener, computed, inject } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { LayoutService } from '../layout.service';

interface ItemNav {
  id: 'dashboard' | 'clientes' | 'pos' | 'membresias' | 'asistencia' | 'reportes';
  ruta: string;
  etiqueta: string;
  /** `null` = visible para cualquier sesión autenticada. */
  permiso: string | null;
  /** Si la ruta todavía no existe en la app, se muestra atenuada y sin enlace. */
  disponible: boolean;
}

const ITEMS_NAV: ItemNav[] = [
  { id: 'dashboard', ruta: '/dashboard', etiqueta: 'Panel', permiso: null, disponible: true },
  { id: 'clientes', ruta: '/clientes', etiqueta: 'Clientes', permiso: 'clientes.ver', disponible: true },
  { id: 'pos', ruta: '/pos', etiqueta: 'Punto de venta', permiso: 'ventas.registrar', disponible: false },
  {
    id: 'membresias',
    ruta: '/membresias',
    etiqueta: 'Membresías',
    permiso: 'membresias.gestionar',
    disponible: false,
  },
  { id: 'asistencia', ruta: '/asistencia', etiqueta: 'Asistencia', permiso: 'clientes.ver', disponible: false },
  { id: 'reportes', ruta: '/reportes', etiqueta: 'Reportes', permiso: 'reportes.ver', disponible: false },
];

/**
 * Lateral de navegación. En escritorio es fijo; en móvil es un cajón
 * deslizante controlado por `LayoutService` (RF-23): oculto por defecto,
 * se abre desde el header, se cierra al navegar, con Escape o pulsando
 * fuera (capa oscura semitransparente).
 */
@Component({
  selector: 'app-aside',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, NgTemplateOutlet],
  templateUrl: './aside.html',
})
export class Aside {
  protected readonly authService = inject(AuthService);
  protected readonly layoutService = inject(LayoutService);
  private readonly router = inject(Router);

  /** Oculta por completo lo que el usuario no puede usar: la autorización
   * real la impone el backend, esto es solo comodidad de interfaz. */
  protected readonly itemsVisibles = computed<ItemNav[]>(() =>
    ITEMS_NAV.filter((item) => item.permiso === null || this.authService.tienePermiso(item.permiso)),
  );

  protected readonly puedeCrearCliente = computed(() => this.authService.tienePermiso('clientes.gestionar'));

  protected irANuevoCliente(): void {
    this.layoutService.cerrar();
    this.router.navigate(['/clientes/nuevo']);
  }

  protected alNavegar(): void {
    this.layoutService.cerrar();
  }

  protected cerrarSesion(): void {
    this.layoutService.cerrar();
    this.authService.logout().subscribe(() => this.router.navigate(['/login']));
  }

  @HostListener('document:keydown.escape')
  protected alPulsarEscape(): void {
    this.layoutService.cerrar();
  }
}
