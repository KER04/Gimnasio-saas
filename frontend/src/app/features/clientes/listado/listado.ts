import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { AuthService } from '../../../core/services/auth.service';
import { ClientesService } from '../../../core/services/clientes.service';
import { PlanesService } from '../../../core/services/planes.service';
import {
  ClienteResumen,
  EstadoFiltroCliente,
  EstadoMembresia,
  FiltroEliminados,
  OPCIONES_ELIMINADOS,
} from '../../../core/models/cliente.model';
import { Plan } from '../../../core/models/plan.model';

/** Opciones del selector "Estado" (valor vacío = todos, sin filtrar). */
const OPCIONES_ESTADO: { valor: EstadoFiltroCliente | ''; etiqueta: string }[] = [
  { valor: '', etiqueta: 'Todos' },
  { valor: 'activa', etiqueta: 'Activa' },
  { valor: 'por_vencer', etiqueta: 'Por vencer' },
  { valor: 'vence_hoy', etiqueta: 'Vence hoy' },
  { valor: 'vencida', etiqueta: 'Vencida' },
  { valor: 'sin_membresia', etiqueta: 'Sin membresía' },
];

/**
 * Listado de clientes (RF-03): buscador SIEMPRE visible (no depende de
 * ninguna otra pantalla), filtros de estado de membresía y de plan, tabla en
 * escritorio y tarjetas apiladas a 360px (RF-23, sin scroll horizontal ni
 * acciones dependientes de :hover).
 */
@Component({
  selector: 'app-clientes-listado',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './listado.html',
})
export class ClientesListado {
  private readonly clientesService = inject(ClientesService);
  private readonly planesService = inject(PlanesService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('clientes.gestionar'));

  protected readonly opcionesEstado = OPCIONES_ESTADO;
  protected readonly planes = signal<Plan[]>([]);

  protected readonly busqueda = new FormControl('', { nonNullable: true });
  protected readonly estado = new FormControl<EstadoFiltroCliente | ''>('', { nonNullable: true });
  protected readonly plan = new FormControl<number | ''>('', { nonNullable: true });

  /** Un filtro más, no una pantalla aparte: los eliminados salen en la misma
   * lista. El borrado es lógico (la ficha y su histórico siguen en la base de
   * datos), así que sin esto un clic de más en "Eliminar" era irreversible
   * salvo tocando la base a mano. */
  protected readonly eliminados = new FormControl<FiltroEliminados>('excluir', { nonNullable: true });
  protected readonly opcionesEliminados = OPCIONES_ELIMINADOS;

  protected readonly clientes = signal<ClienteResumen[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly eliminandoId = signal<number | null>(null);
  protected readonly restaurandoId = signal<number | null>(null);

  protected readonly count = signal(0);
  protected readonly next = signal<string | null>(null);
  protected readonly previous = signal<string | null>(null);
  protected readonly pagina = signal(1);

  /** Rango "X de Y" del pie de la tarjeta (tamaño de página = 20, fijo en
   * el backend: ver `RespuestaPaginada`/`PAGE_SIZE`). */
  protected readonly desde = computed(() => (this.count() === 0 ? 0 : (this.pagina() - 1) * 20 + 1));
  protected readonly hasta = computed(() => Math.min(this.pagina() * 20, this.count()));

  /** Distingue el estado vacío "no hay clientes todavía" del de "la
   * búsqueda/filtro no encontró nada": mismo listado vacío, mensaje distinto.
   *
   * Método normal y NO `computed`: lee `FormControl.value`, que no es una
   * señal. Un `computed` que solo lee valores no reactivos no llega a
   * registrar ninguna dependencia, así que se evaluaría una vez y devolvería
   * ese primer resultado para siempre -- aquí, "no hay filtro" incluso
   * después de buscar. Como método se reevalúa en cada ciclo de detección de
   * cambios, que es justo lo que necesita. */
  protected hayFiltro(): boolean {
    return (
      this.busqueda.value.trim().length > 0
      || this.estado.value !== ''
      || this.plan.value !== ''
      || this.eliminados.value !== 'excluir'
    );
  }

  constructor() {
    // El buscador del header navega a `/clientes?buscar=…`. Sin esto el
    // parámetro se ignoraba por completo y la búsqueda global no hacía nada.
    //
    // Se toma primero del `snapshot`, ANTES de suscribirse y sin emitir
    // evento, para que la carga inicial ya salga filtrada y no se dispare
    // una segunda petición.
    const buscarInicial = this.route.snapshot.queryParamMap.get('buscar') ?? '';
    if (buscarInicial) {
      this.busqueda.setValue(buscarInicial, { emitEvent: false });
    }

    // Búsquedas POSTERIORES desde el header: la ruta es la misma, así que
    // Angular reutiliza el componente y no vuelve a construirlo; si solo se
    // leyera el snapshot, la segunda búsqueda no surtiría efecto. La primera
    // emisión coincide con lo ya fijado arriba y sale por el `return`.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const texto = params.get('buscar') ?? '';
      if (texto === this.busqueda.value) {
        return;
      }
      this.busqueda.setValue(texto, { emitEvent: false });
      this.pagina.set(1);
      this.cargar();
    });

    this.busqueda.valueChanges
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => {
        this.pagina.set(1);
        this.cargar();
      });

    this.estado.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pagina.set(1);
      this.cargar();
    });

    this.plan.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pagina.set(1);
      this.cargar();
    });

    this.eliminados.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pagina.set(1);
      this.cargar();
    });

    this.planesService.listar().subscribe({
      next: (planes) => this.planes.set(planes),
      error: () => this.planes.set([]),
    });

    this.cargar();
  }

  private cargar(): void {
    this.cargando.set(true);
    this.error.set(null);

    const texto = this.busqueda.value.trim() || undefined;
    const estado = this.estado.value || undefined;
    const plan = this.plan.value || undefined;

    this.clientesService.listar(texto, this.pagina(), estado, plan, this.eliminados.value).subscribe({
      next: (respuesta) => {
        this.clientes.set(respuesta.results);
        this.count.set(respuesta.count);
        this.next.set(respuesta.next);
        this.previous.set(respuesta.previous);
        this.cargando.set(false);
      },
      error: (error: unknown) => {
        this.cargando.set(false);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  protected paginaSiguiente(): void {
    if (!this.next()) {
      return;
    }
    this.pagina.update((p) => p + 1);
    this.cargar();
  }

  protected paginaAnterior(): void {
    if (!this.previous()) {
      return;
    }
    this.pagina.update((p) => Math.max(1, p - 1));
    this.cargar();
  }

  protected irAFicha(cliente: ClienteResumen): void {
    // La ficha de un cliente eliminado responde 404 a propósito: primero se
    // restaura y luego se consulta. Sin esta guarda, pinchar una fila de la
    // papelera llevaba a una pantalla de error.
    if (cliente.eliminado_en) {
      return;
    }
    this.router.navigate(['/clientes', cliente.id]);
  }

  protected ver(cliente: ClienteResumen, evento: Event): void {
    evento.stopPropagation();
    this.irAFicha(cliente);
  }

  protected editar(cliente: ClienteResumen, evento: Event): void {
    evento.stopPropagation();
    this.router.navigate(['/clientes', cliente.id, 'editar']);
  }

  protected eliminar(cliente: ClienteResumen, evento: Event): void {
    evento.stopPropagation();
    if (this.eliminandoId() !== null) {
      return;
    }
    const confirmado = confirm(`¿Eliminar a "${cliente.nombre}"? Su histórico de compras se conserva.`);
    if (!confirmado) {
      return;
    }
    this.eliminandoId.set(cliente.id);
    this.clientesService.eliminar(cliente.id).subscribe({
      next: () => {
        this.eliminandoId.set(null);
        this.cargar();
      },
      error: (error: unknown) => {
        this.eliminandoId.set(null);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  /** Devuelve un cliente eliminado a la circulación. Sin confirmación:
   * restaurar no destruye nada y se deshace volviendo a eliminar. */
  protected restaurar(cliente: ClienteResumen, evento: Event): void {
    evento.stopPropagation();
    if (this.restaurandoId() !== null) {
      return;
    }
    this.restaurandoId.set(cliente.id);
    this.clientesService.restaurar(cliente.id).subscribe({
      next: () => {
        this.restaurandoId.set(null);
        this.cargar();
      },
      error: (error: unknown) => {
        this.restaurandoId.set(null);
        this.error.set(this.mensajeDeError(error));
      },
    });
  }

  protected iniciales(nombre: string): string {
    const partes = nombre.trim().split(/\s+/).filter(Boolean);
    if (partes.length === 0) {
      return '?';
    }
    if (partes.length === 1) {
      return partes[0].charAt(0).toUpperCase();
    }
    return (partes[0].charAt(0) + partes[partes.length - 1].charAt(0)).toUpperCase();
  }

  /** Clase del chip de estado de la membresía vigente (RF-16): sin
   * membresía es neutral, no negativo -- no es un error del cliente. */
  protected claseEstado(estado: EstadoMembresia | undefined): string {
    switch (estado) {
      case 'activa':
        return 'badge-success';
      case 'por_vencer':
      case 'vence_hoy':
        return 'badge-warning';
      case 'vencida':
        return 'badge-danger';
      default:
        return 'badge-neutral';
    }
  }

  protected etiquetaEstado(estado: EstadoMembresia | undefined): string {
    switch (estado) {
      case 'activa':
        return 'Activa';
      case 'por_vencer':
        return 'Por vencer';
      case 'vence_hoy':
        return 'Vence hoy';
      case 'vencida':
        return 'Vencida';
      default:
        return 'Sin membresía';
    }
  }

  /**
   * Fecha de vencimiento de la membresía vigente. Sustituye a la columna de
   * "última visita": mientras no exista el control de asistencia, esa
   * columna solo podía decir "Nunca" para todo el mundo, mientras que saber
   * a quién se le acaba la membresía es lo que dispara la gestión de cobro
   * (RF-16).
   *
   * `fecha_fin` llega como `YYYY-MM-DD`; se le añade `T00:00:00` para que se
   * interprete en hora LOCAL (sin eso, `new Date('2026-09-02')` se lee como
   * UTC y en Colombia, UTC-5, mostraría el día anterior).
   */
  /** `eliminado_en` es un INSTANTE, no una fecha suelta: no puede pasar por
   * `fechaVencimiento`, que le concatena `T00:00:00` y produciría `Invalid
   * Date`. */
  protected fechaEliminacion(instanteIso: string): string {
    const fecha = new Date(instanteIso);
    if (Number.isNaN(fecha.getTime())) {
      return instanteIso;
    }
    return fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  protected fechaVencimiento(fechaIso: string): string {
    const fecha = new Date(`${fechaIso}T00:00:00`);
    if (Number.isNaN(fecha.getTime())) {
      return fechaIso;
    }
    return fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  /** Texto de apoyo bajo la fecha. `dias_restantes` lo calcula la base de
   * datos en la zona horaria del gimnasio (`v_membresias_estado`), así que
   * aquí solo se redacta: negativo = ya venció. */
  protected diasRestantes(dias: number): string {
    if (dias < 0) {
      const vencidos = Math.abs(dias);
      return vencidos === 1 ? 'venció ayer' : `venció hace ${vencidos} días`;
    }
    if (dias === 0) {
      return 'vence hoy';
    }
    return dias === 1 ? 'queda 1 día' : `quedan ${dias} días`;
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo cargar el listado de clientes. Inténtalo de nuevo.';
  }
}
