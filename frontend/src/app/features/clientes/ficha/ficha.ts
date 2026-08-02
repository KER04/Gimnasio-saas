import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { ClientesService } from '../../../core/services/clientes.service';
import {
  AsistenciaCliente,
  Cliente,
  CompraCliente,
  DeudaCliente,
  MembresiaResumen,
} from '../../../core/models/cliente.model';

type Pestana = 'datos' | 'membresias' | 'deuda' | 'compras' | 'asistencias';

/**
 * Ficha del cliente (RF-03/RF-09/RF-16): cada pestaña carga su propio
 * endpoint solo la primera vez que se abre, no todas de golpe.
 */
@Component({
  selector: 'app-clientes-ficha',
  imports: [RouterLink],
  templateUrl: './ficha.html',
})
export class ClientesFicha {
  private readonly clientesService = inject(ClientesService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  private readonly clienteId = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('clientes.gestionar'));

  protected readonly cliente = signal<Cliente | null>(null);
  protected readonly cargandoCliente = signal(true);
  protected readonly errorCliente = signal<string | null>(null);

  protected readonly tabActiva = signal<Pestana>('datos');

  protected readonly pestanas: { id: Pestana; etiqueta: string }[] = [
    { id: 'datos', etiqueta: 'Datos' },
    { id: 'membresias', etiqueta: 'Membresías' },
    { id: 'deuda', etiqueta: 'Deuda' },
    { id: 'compras', etiqueta: 'Compras' },
    { id: 'asistencias', etiqueta: 'Asistencias' },
  ];

  // --- Membresías ---
  protected readonly membresias = signal<MembresiaResumen[] | null>(null);
  protected readonly cargandoMembresias = signal(false);
  protected readonly errorMembresias = signal<string | null>(null);

  // --- Deuda ---
  protected readonly deuda = signal<DeudaCliente | null>(null);
  protected readonly cargandoDeuda = signal(false);
  protected readonly errorDeuda = signal<string | null>(null);

  // --- Compras ---
  protected readonly compras = signal<CompraCliente[] | null>(null);
  protected readonly cargandoCompras = signal(false);
  protected readonly errorCompras = signal<string | null>(null);
  protected readonly comprasCount = signal(0);
  protected readonly comprasNext = signal<string | null>(null);
  protected readonly comprasPrevious = signal<string | null>(null);
  protected readonly comprasPagina = signal(1);

  // --- Asistencias ---
  protected readonly asistencias = signal<AsistenciaCliente[] | null>(null);
  protected readonly cargandoAsistencias = signal(false);
  protected readonly errorAsistencias = signal<string | null>(null);
  protected readonly asistenciasCount = signal(0);
  protected readonly asistenciasNext = signal<string | null>(null);
  protected readonly asistenciasPrevious = signal<string | null>(null);
  protected readonly asistenciasPagina = signal(1);

  // --- Eliminar ---
  protected readonly confirmandoEliminar = signal(false);
  protected readonly eliminando = signal(false);
  protected readonly errorEliminar = signal<string | null>(null);

  constructor() {
    this.cargarCliente();
  }

  private cargarCliente(): void {
    this.cargandoCliente.set(true);
    this.errorCliente.set(null);
    this.clientesService.obtener(this.clienteId).subscribe({
      next: (cliente) => {
        this.cliente.set(cliente);
        this.cargandoCliente.set(false);
      },
      error: (error: unknown) => {
        this.cargandoCliente.set(false);
        this.errorCliente.set(this.mensajeDeError(error));
      },
    });
  }

  protected cambiarTab(tab: Pestana): void {
    this.tabActiva.set(tab);
    switch (tab) {
      case 'membresias':
        this.cargarMembresias();
        break;
      case 'deuda':
        this.cargarDeuda();
        break;
      case 'compras':
        this.cargarCompras();
        break;
      case 'asistencias':
        this.cargarAsistencias();
        break;
    }
  }

  private cargarMembresias(): void {
    if (this.membresias() !== null || this.cargandoMembresias()) {
      return;
    }
    this.cargandoMembresias.set(true);
    this.errorMembresias.set(null);
    this.clientesService.membresias(this.clienteId).subscribe({
      next: (datos) => {
        this.membresias.set(datos);
        this.cargandoMembresias.set(false);
      },
      error: (error: unknown) => {
        this.cargandoMembresias.set(false);
        this.errorMembresias.set(this.mensajeDeError(error));
      },
    });
  }

  private cargarDeuda(): void {
    if (this.deuda() !== null || this.cargandoDeuda()) {
      return;
    }
    this.cargandoDeuda.set(true);
    this.errorDeuda.set(null);
    this.clientesService.deuda(this.clienteId).subscribe({
      next: (datos) => {
        this.deuda.set(datos);
        this.cargandoDeuda.set(false);
      },
      error: (error: unknown) => {
        this.cargandoDeuda.set(false);
        this.errorDeuda.set(this.mensajeDeError(error));
      },
    });
  }

  private cargarCompras(): void {
    if (this.compras() !== null || this.cargandoCompras()) {
      return;
    }
    this.cargandoCompras.set(true);
    this.errorCompras.set(null);
    this.clientesService.compras(this.clienteId, this.comprasPagina()).subscribe({
      next: (respuesta) => {
        this.compras.set(respuesta.results);
        this.comprasCount.set(respuesta.count);
        this.comprasNext.set(respuesta.next);
        this.comprasPrevious.set(respuesta.previous);
        this.cargandoCompras.set(false);
      },
      error: (error: unknown) => {
        this.cargandoCompras.set(false);
        this.errorCompras.set(this.mensajeDeError(error));
      },
    });
  }

  protected comprasSiguiente(): void {
    if (!this.comprasNext()) {
      return;
    }
    this.comprasPagina.update((p) => p + 1);
    this.compras.set(null);
    this.cargarCompras();
  }

  protected comprasAnterior(): void {
    if (!this.comprasPrevious()) {
      return;
    }
    this.comprasPagina.update((p) => Math.max(1, p - 1));
    this.compras.set(null);
    this.cargarCompras();
  }

  private cargarAsistencias(): void {
    if (this.asistencias() !== null || this.cargandoAsistencias()) {
      return;
    }
    this.cargandoAsistencias.set(true);
    this.errorAsistencias.set(null);
    this.clientesService.asistencias(this.clienteId, this.asistenciasPagina()).subscribe({
      next: (respuesta) => {
        this.asistencias.set(respuesta.results);
        this.asistenciasCount.set(respuesta.count);
        this.asistenciasNext.set(respuesta.next);
        this.asistenciasPrevious.set(respuesta.previous);
        this.cargandoAsistencias.set(false);
      },
      error: (error: unknown) => {
        this.cargandoAsistencias.set(false);
        this.errorAsistencias.set(this.mensajeDeError(error));
      },
    });
  }

  protected asistenciasSiguiente(): void {
    if (!this.asistenciasNext()) {
      return;
    }
    this.asistenciasPagina.update((p) => p + 1);
    this.asistencias.set(null);
    this.cargarAsistencias();
  }

  protected asistenciasAnterior(): void {
    if (!this.asistenciasPrevious()) {
      return;
    }
    this.asistenciasPagina.update((p) => Math.max(1, p - 1));
    this.asistencias.set(null);
    this.cargarAsistencias();
  }

  protected confirmarEliminar(): void {
    this.confirmandoEliminar.set(true);
  }

  protected cancelarEliminar(): void {
    this.confirmandoEliminar.set(false);
  }

  protected eliminar(): void {
    if (this.eliminando()) {
      return;
    }
    this.eliminando.set(true);
    this.errorEliminar.set(null);
    this.clientesService.eliminar(this.clienteId).subscribe({
      next: () => {
        this.router.navigate(['/clientes']);
      },
      error: (error: unknown) => {
        this.eliminando.set(false);
        this.errorEliminar.set(this.mensajeDeError(error));
      },
    });
  }

  protected badgeMembresia(estado: string): string {
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

  protected etiquetaEstadoMembresia(estado: string): string {
    switch (estado) {
      case 'activa':
        return 'Activa';
      case 'por_vencer':
        return 'Por vencer';
      case 'vence_hoy':
        return 'Vence hoy';
      case 'vencida':
        return 'Vencida';
      case 'cancelada':
        return 'Cancelada';
      default:
        return estado;
    }
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo cargar la información. Inténtalo de nuevo.';
  }
}
