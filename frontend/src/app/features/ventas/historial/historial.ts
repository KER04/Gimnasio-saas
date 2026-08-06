import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { VentasService } from '../../../core/services/ventas.service';
import {
  ETIQUETAS_FORMA_PAGO,
  EstadoVenta,
  FormaPago,
  Venta,
} from '../../../core/models/venta.model';
import { precioParaMostrar } from '../../../core/utils/precio.util';

const ESTADOS: { valor: EstadoVenta | ''; etiqueta: string }[] = [
  { valor: '', etiqueta: 'Todas' },
  { valor: 'pagada', etiqueta: 'Pagadas' },
  { valor: 'parcial', etiqueta: 'Con saldo' },
  { valor: 'pendiente', etiqueta: 'Sin pagar' },
  { valor: 'anulada', etiqueta: 'Anuladas' },
];

/**
 * Historial de ventas: qué se vendió, a quién, cómo se pagó y con qué saldo.
 * Es también el único sitio desde donde se puede ANULAR una venta.
 *
 * Anular no borra nada: el backend crea un movimiento inverso de inventario
 * que devuelve el stock, marca los pagos como anulados y deja la venta con su
 * motivo y su responsable. El histórico se conserva entero -- por eso las
 * ventas anuladas siguen apareciendo en el listado, marcadas.
 */
@Component({
  selector: 'app-ventas-historial',
  imports: [ReactiveFormsModule],
  templateUrl: './historial.html',
})
export class VentasHistorial {
  private readonly ventasService = inject(VentasService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  /** Anular exige un permiso propio, más alto que el de registrar. */
  protected readonly puedeAnular = computed(() => this.authService.tienePermiso('ventas.anular'));

  protected readonly estados = ESTADOS;
  protected readonly formasPago = ETIQUETAS_FORMA_PAGO;

  protected readonly filtroEstado = this.fb.nonNullable.control<EstadoVenta | ''>('');
  protected readonly desde = this.fb.nonNullable.control('');
  protected readonly hasta = this.fb.nonNullable.control('');

  protected readonly ventas = signal<Venta[]>([]);
  protected readonly count = signal(0);
  protected readonly pagina = signal(1);
  protected readonly hayMas = signal(false);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  /** Venta desplegada. Se guarda el id y no el objeto para que, al recargar
   * tras anular, el detalle abierto muestre el estado nuevo y no una copia
   * vieja. */
  protected readonly detalleAbierto = signal<number | null>(null);

  protected readonly ventaAnulando = signal<Venta | null>(null);
  protected readonly anulando = signal(false);
  protected readonly errorAnular = signal<string | null>(null);
  protected readonly formAnular = this.fb.nonNullable.group({
    motivo: this.fb.nonNullable.control('', [Validators.required]),
  });

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(null);
    this.ventasService
      .listar({
        estado: this.filtroEstado.value || undefined,
        desde: this.desde.value || undefined,
        hasta: this.hasta.value || undefined,
        page: this.pagina(),
      })
      .subscribe({
        next: (respuesta) => {
          this.ventas.set(respuesta.results);
          this.count.set(respuesta.count);
          this.hayMas.set(respuesta.next !== null);
          this.cargando.set(false);
        },
        error: (error: unknown) => {
          this.cargando.set(false);
          this.error.set(this.mensajeDeError(error, 'No se pudo cargar el historial de ventas.'));
        },
      });
  }

  protected filtrar(estado: EstadoVenta | ''): void {
    this.filtroEstado.setValue(estado);
    this.pagina.set(1);
    this.cargar();
  }

  protected aplicarFechas(): void {
    this.pagina.set(1);
    this.cargar();
  }

  protected paginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.update((p) => p - 1);
      this.cargar();
    }
  }

  protected paginaSiguiente(): void {
    if (this.hayMas()) {
      this.pagina.update((p) => p + 1);
      this.cargar();
    }
  }

  protected alternarDetalle(venta: Venta): void {
    this.detalleAbierto.update((abierto) => (abierto === venta.id ? null : venta.id));
  }

  // -----------------------------------------------------------------------
  // Anulación
  // -----------------------------------------------------------------------

  protected abrirAnular(venta: Venta): void {
    this.errorAnular.set(null);
    this.formAnular.reset({ motivo: '' });
    this.ventaAnulando.set(venta);
  }

  protected cerrarAnular(): void {
    this.ventaAnulando.set(null);
    this.errorAnular.set(null);
  }

  protected anular(): void {
    const venta = this.ventaAnulando();
    if (this.anulando() || venta === null) {
      return;
    }
    this.formAnular.markAllAsTouched();
    if (this.formAnular.invalid) {
      return;
    }

    this.anulando.set(true);
    this.errorAnular.set(null);

    this.ventasService.anular(venta.id, { motivo: this.formAnular.getRawValue().motivo.trim() }).subscribe({
      next: () => {
        this.anulando.set(false);
        this.ventaAnulando.set(null);
        this.cargar();
      },
      error: (error: unknown) => {
        this.anulando.set(false);
        this.errorAnular.set(this.mensajeDeError(error, 'No se pudo anular la venta.'));
      },
    });
  }

  // -----------------------------------------------------------------------
  // Presentación
  // -----------------------------------------------------------------------

  protected dinero(valor: string): string {
    return precioParaMostrar(valor);
  }

  protected cantidad(valor: string): string {
    const numero = Number(valor);
    return Number.isInteger(numero) ? String(numero) : valor;
  }

  protected fecha(iso: string): string {
    const f = new Date(iso);
    return Number.isNaN(f.getTime())
      ? iso
      : f.toLocaleString('es-CO', {
          day: 'numeric',
          month: 'short',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
        });
  }

  protected etiquetaEstado(estado: EstadoVenta): string {
    switch (estado) {
      case 'pagada':
        return 'Pagada';
      case 'parcial':
        return 'Con saldo';
      case 'pendiente':
        return 'Sin pagar';
      default:
        return 'Anulada';
    }
  }

  protected claseEstado(estado: EstadoVenta): string {
    switch (estado) {
      case 'pagada':
        return 'badge-success';
      case 'parcial':
        return 'badge-warning';
      case 'pendiente':
        return 'badge-danger';
      default:
        return 'badge-neutral';
    }
  }

  protected etiquetaFormaPago(forma: FormaPago): string {
    return this.formasPago[forma] ?? forma;
  }

  protected irAlCliente(venta: Venta): void {
    if (venta.cliente !== null) {
      this.router.navigate(['/clientes', venta.cliente], { queryParams: { tab: 'deuda' } });
    }
  }

  private mensajeDeError(error: unknown, porDefecto: string): string {
    if (error instanceof HttpErrorResponse && error.error) {
      const cuerpo = error.error as Record<string, unknown>;
      if (typeof cuerpo['detail'] === 'string') {
        return cuerpo['detail'];
      }
      const primero = Object.values(cuerpo)[0];
      if (typeof primero === 'string') {
        return primero;
      }
      if (Array.isArray(primero) && typeof primero[0] === 'string') {
        return primero[0];
      }
    }
    return porDefecto;
  }
}
