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

  /**
   * Clases de la navegación, en dos juegos EXCLUYENTES.
   *
   * No se suman a un juego base: si el estilo de hover del elemento normal
   * siguiera aplicándose al seleccionado, le pondría fondo casi blanco
   * manteniendo el texto blanco y la opción activa quedaría ilegible al pasar
   * el ratón. Cada estado trae su propio hover, y solo uno se aplica.
   */
  private static readonly BASE =
    'flex min-h-11 items-center gap-3 rounded-field px-3 py-2 transition-colors';

  protected readonly CLASES_NAV_ACTIVO =
    `${Aside.BASE} bg-primary-500 text-white hover:bg-primary-600`;

  protected readonly CLASES_NAV_INACTIVO =
    `${Aside.BASE} text-text-principal hover:bg-neutral-50`;

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
