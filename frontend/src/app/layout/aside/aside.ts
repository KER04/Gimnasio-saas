import { Component, HostListener, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map, startWith } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { LayoutService } from '../layout.service';

interface ItemNav {
  id: string;
  ruta: string;
  etiqueta: string;
  /** `null` = visible para cualquier sesión autenticada. */
  permiso: string | null;
}

interface GrupoNav {
  id: string;
  etiqueta: string;
  items: ItemNav[];
}

/**
 * Lo que se usa TODO EL DÍA, sin agrupar.
 *
 * Asistencia y punto de venta se pulsan decenas de veces en una jornada:
 * meterlos dentro de un desplegable cobraría un clic de peaje en lo más
 * frecuente, que es justo lo contrario de lo que un menú debe hacer. Los
 * grupos existen para lo que se abre de vez en cuando.
 */
const ITEMS_DIRECTOS: ItemNav[] = [
  { id: 'dashboard', ruta: '/dashboard', etiqueta: 'Panel', permiso: null },
  { id: 'asistencia', ruta: '/asistencia', etiqueta: 'Asistencia', permiso: 'clientes.ver' },
  { id: 'pos', ruta: '/pos', etiqueta: 'Punto de venta', permiso: 'ventas.registrar' },
  { id: 'clientes', ruta: '/clientes', etiqueta: 'Clientes', permiso: 'clientes.ver' },
];

const GRUPOS: GrupoNav[] = [
  {
    id: 'entrenamiento',
    etiqueta: 'Entrenamiento',
    items: [
      // "Rutinas" y no "Entrenamiento": el grupo ya se llama así, y
      // Entrenamiento › Entrenamiento no dice nada.
      { id: 'rutinas', ruta: '/entrenamiento', etiqueta: 'Rutinas', permiso: 'rutinas.gestionar' },
      { id: 'medidas', ruta: '/medidas', etiqueta: 'Medidas', permiso: 'medidas.gestionar' },
    ],
  },
  {
    id: 'catalogo',
    etiqueta: 'Catálogo',
    items: [
      { id: 'membresias', ruta: '/membresias', etiqueta: 'Membresías', permiso: 'membresias.gestionar' },
      { id: 'inventario', ruta: '/inventario', etiqueta: 'Inventario', permiso: 'inventario.ver' },
    ],
  },
  {
    id: 'consultas',
    etiqueta: 'Consultas',
    items: [
      { id: 'reportes', ruta: '/reportes', etiqueta: 'Reportes', permiso: 'reportes.ver' },
      // El histórico va aquí y no junto al punto de venta: el POS es donde
      // vendes, esto es mirar hacia atrás para consultar o anular.
      { id: 'ventas', ruta: '/ventas', etiqueta: 'Historial de ventas', permiso: 'ventas.registrar' },
    ],
  },
  {
    id: 'configuracion',
    etiqueta: 'Configuración',
    items: [
      { id: 'usuarios', ruta: '/usuarios', etiqueta: 'Usuarios', permiso: 'config.usuarios' },
      { id: 'sedes', ruta: '/sedes', etiqueta: 'Sedes', permiso: 'config.sedes' },
    ],
  },
];

const CLAVE_ABIERTOS = 'gimnasio_grupos_abiertos';

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

  /** La URL actual, de forma REACTIVA: `router.url` no lo es, y de él depende
   * qué grupo aparece abierto. */
  private readonly urlActual = toSignal(
    this.router.events.pipe(
      filter((evento): evento is NavigationEnd => evento instanceof NavigationEnd),
      map((evento) => evento.urlAfterRedirects),
      startWith(this.router.url),
    ),
    { initialValue: this.router.url },
  );

  /** Grupos que el usuario abrió a mano. Se recuerdan entre navegaciones y
   * entre sesiones: volver a cerrarlos en cada clic sería trabajo repetido. */
  private readonly abiertosManualmente = signal<Set<string>>(this.leerAbiertos());

  private leerAbiertos(): Set<string> {
    try {
      const guardado = localStorage.getItem(CLAVE_ABIERTOS);
      return new Set<string>(guardado ? JSON.parse(guardado) : []);
    } catch {
      // Modo incógnito o dato corrupto: se empieza con todos cerrados.
      return new Set<string>();
    }
  }

  private puede(permiso: string | null): boolean {
    return permiso === null || this.authService.tienePermiso(permiso);
  }

  /** Oculta por completo lo que el usuario no puede usar: la autorización
   * real la impone el backend, esto es solo comodidad de interfaz. */
  protected readonly itemsDirectos = computed(() =>
    ITEMS_DIRECTOS.filter((item) => this.puede(item.permiso)),
  );

  private readonly gruposFiltrados = computed(() =>
    GRUPOS.map((grupo) => ({
      ...grupo,
      items: grupo.items.filter((item) => this.puede(item.permiso)),
    })).filter((grupo) => grupo.items.length > 0),
  );

  /**
   * Los grupos que de verdad se dibujan como desplegable.
   *
   * Un grupo con UN solo ítem visible no lo es: un desplegable para un único
   * elemento es peor que ninguno, porque esconde tras un clic algo que cabía
   * a la vista. Esos se aplanan en `itemsSueltos`. Y los que se quedan sin
   * ítems desaparecen: a un entrenador no le sale "Configuración" vacía.
   */
  protected readonly grupos = computed(() =>
    this.gruposFiltrados().filter((grupo) => grupo.items.length > 1),
  );

  protected readonly itemsSueltos = computed(() =>
    this.gruposFiltrados()
      .filter((grupo) => grupo.items.length === 1)
      .map((grupo) => grupo.items[0]),
  );

  /**
   * Un grupo está abierto si el usuario lo abrió O si estás dentro de él.
   *
   * Lo segundo no es un adorno: si entras a Medidas y "Entrenamiento"
   * apareciera cerrado, el menú dejaría de decirte dónde estás.
   */
  protected estaAbierto(grupo: GrupoNav): boolean {
    if (this.abiertosManualmente().has(grupo.id)) {
      return true;
    }
    const url = this.urlActual();
    return grupo.items.some((item) => url.startsWith(item.ruta));
  }

  protected alternarGrupo(grupo: GrupoNav): void {
    this.abiertosManualmente.update((abiertos) => {
      const copia = new Set(abiertos);
      if (copia.has(grupo.id)) {
        copia.delete(grupo.id);
      } else {
        copia.add(grupo.id);
      }
      try {
        localStorage.setItem(CLAVE_ABIERTOS, JSON.stringify([...copia]));
      } catch {
        // Si no se puede guardar, el estado sigue vivo en esta pestaña.
      }
      return copia;
    });
  }

  protected readonly puedeCrearCliente = computed(() =>
    this.authService.tienePermiso('clientes.gestionar'),
  );

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
   */
  protected readonly CLASES_NAV_ACTIVO =
    `${Aside.BASE} bg-primary text-on-primary font-semibold hover:bg-primary-container`;

  protected readonly CLASES_NAV_INACTIVO =
    `${Aside.BASE} text-on-surface-variant hover:bg-surface-container-low`;

  /** Dentro de un grupo los enlaces van indentados: la jerarquía tiene que
   * verse sin leer. */
  private static readonly BASE_HIJO = `${Aside.BASE} ml-3`;

  protected readonly CLASES_HIJO_ACTIVO =
    `${Aside.BASE_HIJO} bg-primary text-on-primary font-semibold hover:bg-primary-container`;

  protected readonly CLASES_HIJO_INACTIVO =
    `${Aside.BASE_HIJO} text-on-surface-variant hover:bg-surface-container-low`;

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
