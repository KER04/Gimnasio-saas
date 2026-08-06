import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { PlataformaService } from '../../../core/services/plataforma.service';
import {
  ETIQUETAS_ESTADO_TENANT,
  EstadoTenant,
  OPCIONES_ESTADO_TENANT,
  TenantResumen,
} from '../../../core/models/plataforma.model';

/** Colores del estado del contrato. Prueba y mora avisan sin alarmar;
 * suspendido y cancelado sí tienen que saltar a la vista. */
const CLASES_ESTADO: Record<EstadoTenant, string> = {
  // No hay tokens `info-*` en el tema; el contenedor primario es el color
  // "informativo" que ya usa el resto de la aplicación.
  prueba: 'bg-primary-container text-on-primary-container',
  activo: 'bg-success-bg text-success-text',
  mora: 'bg-warning-bg text-warning-text',
  suspendido: 'bg-danger-bg text-danger-text',
  cancelado: 'bg-surface-container-highest text-on-surface-variant',
};

@Component({
  selector: 'app-plataforma-gimnasios',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './gimnasios.html',
})
export class PlataformaGimnasios {
  private readonly plataformaService = inject(PlataformaService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  /** Dar de alta es cosa del rol `administrador`; soporte solo consulta. */
  protected readonly puedeGestionar = this.plataformaService.esAdministrador;

  protected readonly opcionesEstado = OPCIONES_ESTADO_TENANT;

  protected readonly buscar = new FormControl('', { nonNullable: true });
  protected readonly estado = new FormControl<EstadoTenant | ''>('', { nonNullable: true });

  protected readonly gimnasios = signal<TenantResumen[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly count = signal(0);
  protected readonly next = signal<string | null>(null);
  protected readonly previous = signal<string | null>(null);
  protected readonly pagina = signal(1);

  protected readonly desde = computed(() => (this.count() === 0 ? 0 : (this.pagina() - 1) * 20 + 1));
  protected readonly hasta = computed(() => Math.min(this.pagina() * 20, this.count()));

  /** Total de clientes de toda la cartera, para la tarjeta de cabecera. Suma
   * SOLO la página actual, y por eso se rotula como tal: sumar todo exigiría
   * un endpoint de agregados que hoy no existe, y presentar la suma de una
   * página como si fuera el total sería sencillamente mentir. */
  protected readonly clientesEnPagina = computed(() =>
    this.gimnasios().reduce((total, g) => total + (g.clientes ?? 0), 0),
  );

  constructor() {
    this.buscar.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.pagina.set(1);
        this.cargar();
      });

    this.estado.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => {
      this.pagina.set(1);
      this.cargar();
    });

    this.cargar();
  }

  /** Método y NO `computed`: lee `FormControl.value`, que no es una señal.
   * Un `computed` no registraría dependencia y se quedaría con el primer
   * valor para siempre. */
  protected hayFiltro(): boolean {
    return this.buscar.value.trim().length > 0 || this.estado.value !== '';
  }

  private cargar(): void {
    this.cargando.set(true);
    this.error.set(null);

    this.plataformaService
      .listarTenants({
        buscar: this.buscar.value.trim() || undefined,
        estado: this.estado.value,
        page: this.pagina(),
      })
      .subscribe({
        next: (respuesta) => {
          this.gimnasios.set(respuesta.results);
          this.count.set(respuesta.count);
          this.next.set(respuesta.next);
          this.previous.set(respuesta.previous);
          this.cargando.set(false);
        },
        error: (error: unknown) => {
          this.cargando.set(false);
          this.error.set(this.mensaje(error));
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

  protected verFicha(gimnasio: TenantResumen): void {
    this.router.navigate(['/plataforma/gimnasios', gimnasio.uuid_publico]);
  }

  protected etiquetaEstado(estado: EstadoTenant): string {
    return ETIQUETAS_ESTADO_TENANT[estado];
  }

  protected claseEstado(estado: EstadoTenant): string {
    return `inline-block rounded-full px-2 py-0.5 text-xs font-medium ${CLASES_ESTADO[estado]}`;
  }

  protected numero(valor: number | null): string {
    return valor === null ? '—' : valor.toLocaleString('es-CO');
  }

  /** `ultima_venta` es un INSTANTE. Sale como "hace 3 días" porque lo que
   * interesa de un vistazo es si el gimnasio sigue vivo, no la fecha exacta. */
  protected actividad(instante: string | null): string {
    if (instante === null) {
      return 'Sin ventas';
    }
    const fecha = new Date(instante);
    if (Number.isNaN(fecha.getTime())) {
      return '—';
    }
    const dias = Math.floor((Date.now() - fecha.getTime()) / 86_400_000);
    if (dias <= 0) {
      return 'Hoy';
    }
    if (dias === 1) {
      return 'Ayer';
    }
    if (dias < 30) {
      return `Hace ${dias} días`;
    }
    return fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  protected iniciales(nombre: string): string {
    const partes = nombre.trim().split(/\s+/).filter(Boolean);
    if (partes.length === 0) {
      return '?';
    }
    return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase();
  }

  private mensaje(error: unknown): string {
    if (error instanceof HttpErrorResponse && error.status === 0) {
      return 'No se pudo conectar con el servidor.';
    }
    return 'No se pudieron cargar los gimnasios.';
  }
}
