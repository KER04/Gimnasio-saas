import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { AuthService } from '../../../core/services/auth.service';
import { ClientesService } from '../../../core/services/clientes.service';
import { ClienteResumen } from '../../../core/models/cliente.model';

/**
 * Listado de clientes (RF-03): buscador SIEMPRE visible (no depende de
 * ninguna otra pantalla), tabla en escritorio y tarjetas apiladas a 360px
 * (RF-23, sin scroll horizontal).
 */
@Component({
  selector: 'app-clientes-listado',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './listado.html',
})
export class ClientesListado {
  private readonly clientesService = inject(ClientesService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('clientes.gestionar'));

  protected readonly busqueda = new FormControl('', { nonNullable: true });

  protected readonly clientes = signal<ClienteResumen[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly count = signal(0);
  protected readonly next = signal<string | null>(null);
  protected readonly previous = signal<string | null>(null);
  protected readonly pagina = signal(1);

  /** Distingue el estado vacío "no hay clientes todavía" del de "la
   * búsqueda no encontró nada": mismo listado vacío, mensaje distinto. */
  protected readonly hayFiltro = computed(() => this.busqueda.value.trim().length > 0);

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

    this.cargar();
  }

  private cargar(): void {
    this.cargando.set(true);
    this.error.set(null);

    const texto = this.busqueda.value.trim() || undefined;
    this.clientesService.listar(texto, this.pagina()).subscribe({
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
