import { Component, HostListener, computed, inject } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { LayoutService } from '../layout.service';

interface ItemNav {
  id:
    | 'dashboard'
    | 'clientes'
    | 'pos'
    | 'ventas'
    | 'inventario'
    | 'membresias'
    | 'asistencia'
    | 'reportes'
    | 'entrenamiento'
    | 'medidas'
    | 'usuarios'
    | 'sedes';
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
  { id: 'pos', ruta: '/pos', etiqueta: 'Punto de venta', permiso: 'ventas.registrar', disponible: true },
  { id: 'ventas', ruta: '/ventas', etiqueta: 'Ventas', permiso: 'ventas.registrar', disponible: true },
  { id: 'inventario', ruta: '/inventario', etiqueta: 'Inventario', permiso: 'inventario.ver', disponible: true },
  {
    id: 'membresias',
    ruta: '/membresias',
    etiqueta: 'Membresías',
    permiso: 'membresias.gestionar',
    disponible: true,
  },
  { id: 'asistencia', ruta: '/asistencia', etiqueta: 'Asistencia', permiso: 'clientes.ver', disponible: true },
  { id: 'reportes', ruta: '/reportes', etiqueta: 'Reportes', permiso: 'reportes.ver', disponible: true },
  {
    id: 'entrenamiento',
    ruta: '/entrenamiento',
    etiqueta: 'Entrenamiento',
    permiso: 'rutinas.gestionar',
    disponible: true,
  },
  { id: 'medidas', ruta: '/medidas', etiqueta: 'Medidas', permiso: 'medidas.gestionar', disponible: true },
  {
    id: 'usuarios',
    ruta: '/usuarios',
    etiqueta: 'Usuarios',
    permiso: 'config.usuarios',
    disponible: true,
  },
  { id: 'sedes', ruta: '/sedes', etiqueta: 'Sedes', permiso: 'config.sedes', disponible: true },
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
    'flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 transition-colors';

  /**
   * Relleno primario SÓLIDO, el mismo morado del botón "Nuevo cliente"
   * (`btn-primary` usa `--color-primary`), para que la opción activa se lea
   * de un vistazo y no como un tinte lavado.
   *
   * El texto pasa a `on-primary` (blanco) obligatoriamente: sobre este fondo
   * el `on-surface` casi negro de antes quedaría ilegible. Contrastes
   * medidos: blanco sobre `primary` 9.35:1 (AAA) y sobre el
   * `primary-container` del hover 6.44:1 (AA) -- ambos por encima del 4.5:1
   * exigible, que es la condición para poder subir la intensidad.
   *
   * Sin barra indicadora a la izquierda: el propio relleno redondeado marca
   * la selección, y una barra encima de él no añadiría información.
   */
  protected readonly CLASES_NAV_ACTIVO =
    `${Aside.BASE} bg-primary text-on-primary font-semibold hover:bg-primary-container`;

  protected readonly CLASES_NAV_INACTIVO =
    `${Aside.BASE} text-on-surface-variant hover:bg-surface-container-low`;

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
