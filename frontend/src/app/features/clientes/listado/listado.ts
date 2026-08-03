import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { AuthService } from '../../../core/services/auth.service';
import { ClientesService } from '../../../core/services/clientes.service';
import { PlanesService } from '../../../core/services/planes.service';
import { ClienteResumen, EstadoFiltroCliente, EstadoMembresia } from '../../../core/models/cliente.model';
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
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('clientes.gestionar'));

  protected readonly opcionesEstado = OPCIONES_ESTADO;
  protected readonly planes = signal<Plan[]>([]);

  protected readonly busqueda = new FormControl('', { nonNullable: true });
  protected readonly estado = new FormControl<EstadoFiltroCliente | ''>('', { nonNullable: true });
  protected readonly plan = new FormControl<number | ''>('', { nonNullable: true });

  protected readonly clientes = signal<ClienteResumen[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly eliminandoId = signal<number | null>(null);

  protected readonly count = signal(0);
  protected readonly next = signal<string | null>(null);
  protected readonly previous = signal<string | null>(null);
  protected readonly pagina = signal(1);

  /** Rango "X de Y" del pie de la tarjeta (tamaño de página = 20, fijo en
   * el backend: ver `RespuestaPaginada`/`PAGE_SIZE`). */
  protected readonly desde = computed(() => (this.count() === 0 ? 0 : (this.pagina() - 1) * 20 + 1));
  protected readonly hasta = computed(() => Math.min(this.pagina() * 20, this.count()));

  /** Distingue el estado vacío "no hay clientes todavía" del de "la
   * búsqueda/filtro no encontró nada": mismo listado vacío, mensaje distinto. */
  protected readonly hayFiltro = computed(
    () => this.busqueda.value.trim().length > 0 || this.estado.value !== '' || this.plan.value !== '',
  );

  constructor() {
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

    this.clientesService.listar(texto, this.pagina(), estado, plan).subscribe({
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

  /** Fecha relativa legible de la última visita (asistencia). `null` es
   * "nunca vino", no un dato faltante. */
  protected ultimaVisita(fechaIso: string | null): string {
    if (!fechaIso) {
      return 'Nunca';
    }
    const fecha = new Date(fechaIso);
    const ahora = new Date();
    const inicioHoy = new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate());
    const inicioFecha = new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate());
    const diasTranscurridos = Math.round((inicioHoy.getTime() - inicioFecha.getTime()) / 86_400_000);

    if (diasTranscurridos === 0) {
      const hora = fecha.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false });
      return `Hoy, ${hora}`;
    }
    if (diasTranscurridos === 1) {
      return 'Ayer';
    }
    if (diasTranscurridos > 1 && diasTranscurridos < 30) {
      return `Hace ${diasTranscurridos} días`;
    }
    return fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
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
