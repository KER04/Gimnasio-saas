import { Component, DestroyRef, ElementRef, HostListener, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged, of, switchMap } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { AuthService } from '../../core/services/auth.service';
import { ClientesService } from '../../core/services/clientes.service';
import { MembresiasService } from '../../core/services/membresias.service';
import { MembresiaPorVencer } from '../../core/models/membresia.model';
import { ClienteResumen, EstadoMembresia } from '../../core/models/cliente.model';
import { LayoutService } from '../layout.service';

/** Caracteres mínimos antes de consultar. Con menos, cualquier tecleo
 * devolvería medio padrón y la sugerencia no ayudaría a nadie. */
const MINIMO_PARA_SUGERIR = 2;

/** Cuántas sugerencias se pintan. El endpoint devuelve la página entera
 * (20); esto es un atajo, no un listado -- para ver todo está Enter. */
const MAX_SUGERENCIAS = 6;

/**
 * Barra superior: marca del gimnasio, buscador global de clientes (RF-03,
 * disponible desde cualquier pantalla) y el chip de usuario con el menú de
 * cierre de sesión (RF-23: se abre con clic, nunca con hover).
 */
@Component({
  selector: 'app-header',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './header.html',
})
export class Header {
  protected readonly authService = inject(AuthService);
  protected readonly layoutService = inject(LayoutService);
  private readonly router = inject(Router);
  private readonly elementRef = inject(ElementRef<HTMLElement>);

  private readonly membresiasService = inject(MembresiasService);
  private readonly clientesService = inject(ClientesService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly busqueda = new FormControl('', { nonNullable: true });
  protected readonly menuAbierto = signal(false);

  // --- Sugerencias del buscador ---
  protected readonly sugerencias = signal<ClienteResumen[]>([]);
  protected readonly buscando = signal(false);
  /** Solo se despliega tras teclear; así no salta al enfocar el campo. */
  protected readonly sugerenciasAbierto = signal(false);

  /** Buscar clientes exige `clientes.ver`. Sin permiso no se sugiere nada
   * (el buscador sigue visible, pero no consulta). */
  protected readonly puedeBuscar = computed(() => this.authService.tienePermiso('clientes.ver'));

  // --- Avisos de vencimiento (RF-16) ---
  // La campana NO es decorativa: muestra el tablero real de
  // `/api/membresias/por-vencer/` (vencidas, vencen hoy y por vencer). El
  // umbral lo decide cada gimnasio con `dias_aviso_vencimiento`, no esta
  // pantalla.
  protected readonly avisos = signal<MembresiaPorVencer[]>([]);
  protected readonly avisosAbierto = signal(false);

  /** El tablero exige `reportes.ver`. Sin ese permiso la campana ni se
   * pinta: pedir el endpoint solo daría un 403. */
  protected readonly puedeVerAvisos = computed(() => this.authService.tienePermiso('reportes.ver'));

  /** Las ya vencidas y las que vencen hoy se cuentan aparte porque son las
   * que exigen llamar HOY; el resto es aviso anticipado. */
  protected readonly avisosUrgentes = computed(
    () => this.avisos().filter((a) => a.dias_restantes <= 0).length,
  );

  constructor() {
    // Sugerencias mientras se escribe.
    //
    // `switchMap` y no `mergeMap`: al teclear rápido se encadenan varias
    // peticiones y solo interesa la última. Con `mergeMap`, una respuesta
    // lenta de "ma" podría llegar DESPUÉS de la de "maria" y pisar los
    // resultados buenos con los de un texto que ya no está escrito.
    if (this.puedeBuscar()) {
      this.busqueda.valueChanges
        .pipe(
          debounceTime(250),
          distinctUntilChanged(),
          switchMap((texto) => {
            const limpio = texto.trim();
            if (limpio.length < MINIMO_PARA_SUGERIR) {
              this.buscando.set(false);
              return of<ClienteResumen[]>([]);
            }
            this.buscando.set(true);
            return this.clientesService.listar(limpio).pipe(
              map((respuesta) => respuesta.results.slice(0, MAX_SUGERENCIAS)),
              // Un fallo de red no puede romper el header: se apaga la lista
              // y el usuario siempre puede pulsar Enter para la búsqueda
              // completa, que muestra su propio error.
              catchError(() => of<ClienteResumen[]>([])),
            );
          }),
          takeUntilDestroyed(this.destroyRef),
        )
        .subscribe((resultados) => {
          this.buscando.set(false);
          this.sugerencias.set(resultados);
          this.sugerenciasAbierto.set(this.busqueda.value.trim().length >= MINIMO_PARA_SUGERIR);
        });
    }

    if (this.puedeVerAvisos()) {
      this.membresiasService.porVencer().subscribe({
        next: (avisos) => this.avisos.set(avisos),
        // Un fallo aquí no puede romper la barra superior de toda la app:
        // sin avisos, la campana sencillamente sale a cero.
        error: () => this.avisos.set([]),
      });
    }
  }

  protected alternarAvisos(): void {
    this.avisosAbierto.update((abierto) => !abierto);
    this.menuAbierto.set(false);
  }

  protected irAlCliente(aviso: MembresiaPorVencer): void {
    this.avisosAbierto.set(false);
    this.router.navigate(['/clientes', aviso.cliente_id]);
  }

  protected claseAviso(estado: EstadoMembresia): string {
    switch (estado) {
      case 'vencida':
        return 'badge-danger';
      case 'vence_hoy':
      case 'por_vencer':
        return 'badge-warning';
      default:
        return 'badge-neutral';
    }
  }

  /** Mismo criterio de redacción que el listado de clientes. */
  protected textoAviso(dias: number): string {
    if (dias < 0) {
      const vencidos = Math.abs(dias);
      return vencidos === 1 ? 'venció ayer' : `venció hace ${vencidos} días`;
    }
    if (dias === 0) {
      return 'vence hoy';
    }
    return dias === 1 ? 'vence mañana' : `vence en ${dias} días`;
  }

  protected readonly nombreCompleto = computed(() => this.authService.sesion()?.nombre ?? '');

  protected readonly iniciales = computed(() => this.inicialesDe(this.nombreCompleto()));

  /** Iniciales de un nombre: la del primer nombre y la del último apellido.
   * Se usa para el avatar del usuario y para el de cada sugerencia. */
  protected inicialesDe(nombre: string): string {
    const partes = nombre.trim().split(/\s+/).filter(Boolean);
    if (partes.length === 0) {
      return '?';
    }
    if (partes.length === 1) {
      return partes[0].charAt(0).toUpperCase();
    }
    return (partes[0].charAt(0) + partes[partes.length - 1].charAt(0)).toUpperCase();
  }

  protected buscar(evento: Event): void {
    // Sin esto el navegador haría el envío nativo del formulario y recargaría
    // la página entera, perdiendo el estado de la aplicación.
    evento.preventDefault();
    const texto = this.busqueda.value.trim();
    this.limpiarBuscador();
    this.router.navigate(['/clientes'], texto ? { queryParams: { buscar: texto } } : {});
  }

  /** Salta directamente a la ficha del cliente elegido, que es lo que se
   * espera de una sugerencia: el listado filtrado ya lo da Enter. */
  protected irASugerencia(cliente: ClienteResumen): void {
    this.limpiarBuscador();
    this.router.navigate(['/clientes', cliente.id]);
  }

  private limpiarBuscador(): void {
    // `emitEvent: false`: vaciar el campo no debe disparar otra consulta.
    this.busqueda.setValue('', { emitEvent: false });
    this.sugerencias.set([]);
    this.sugerenciasAbierto.set(false);
    this.buscando.set(false);
    this.menuAbierto.set(false);
  }

  protected alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  /** El enlace a "Mi cuenta" navega solo; esto únicamente recoge el
   * desplegable, que si no se quedaría abierto sobre la página nueva. */
  protected cerrarMenu(): void {
    this.menuAbierto.set(false);
  }

  protected cerrarSesion(): void {
    this.menuAbierto.set(false);
    this.authService.logout().subscribe(() => this.router.navigate(['/login']));
  }

  /** Cierra los desplegables al pulsar fuera de ellos. */
  @HostListener('document:click', ['$event'])
  protected alClicarFuera(evento: MouseEvent): void {
    if (this.elementRef.nativeElement.contains(evento.target as Node)) {
      return;
    }
    this.menuAbierto.set(false);
    this.avisosAbierto.set(false);
    this.sugerenciasAbierto.set(false);
  }

  @HostListener('document:keydown.escape')
  protected alPulsarEscape(): void {
    this.menuAbierto.set(false);
    this.avisosAbierto.set(false);
    this.sugerenciasAbierto.set(false);
  }
}
