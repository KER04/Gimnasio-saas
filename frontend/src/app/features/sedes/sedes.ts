import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import {
  SedeAdmin,
  SedesAdminService,
} from '../../core/services/sedes-admin.service';

type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Sedes del gimnasio.
 *
 * Una sede no se borra nunca: ventas, gastos y stock la protegen en la base
 * de datos, y el histórico tiene que poder decir dónde ocurrió cada cosa.
 * Cerrarla la deja fuera de circulación conservándolo todo.
 */
@Component({
  selector: 'app-sedes',
  imports: [ReactiveFormsModule],
  templateUrl: './sedes.html',
})
export class SedesGestion {
  private readonly sedesService = inject(SedesAdminService);
  private readonly fb = inject(FormBuilder);

  protected readonly sedes = signal<SedeAdmin[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly aviso = signal<string | null>(null);

  protected readonly panelAbierto = signal(false);
  protected readonly editando = signal<SedeAdmin | null>(null);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});
  protected readonly ocupadoId = signal<number | null>(null);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', [Validators.required]],
    direccion: ['', [Validators.required]],
    telefono: [''],
    nit: [''],
    prefijo_comprobante: ['F'],
    encabezado_recibo: [''],
  });

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.sedesService.listar().subscribe({
      next: (sedes) => {
        this.sedes.set(sedes);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar las sedes.');
      },
    });
  }

  protected abrirAlta(): void {
    this.editando.set(null);
    this.erroresCampo.set({});
    this.formulario.reset({ prefijo_comprobante: 'F' });
    this.panelAbierto.set(true);
  }

  protected abrirEdicion(sede: SedeAdmin): void {
    this.editando.set(sede);
    this.erroresCampo.set({});
    this.formulario.reset({
      nombre: sede.nombre,
      direccion: sede.direccion,
      telefono: sede.telefono ?? '',
      nit: sede.nit ?? '',
      prefijo_comprobante: sede.prefijo_comprobante,
      encabezado_recibo: sede.encabezado_recibo ?? '',
    });
    this.panelAbierto.set(true);
  }

  protected cerrarPanel(): void {
    this.panelAbierto.set(false);
    this.editando.set(null);
    this.erroresCampo.set({});
  }

  protected guardar(): void {
    if (this.guardando()) {
      return;
    }
    this.formulario.markAllAsTouched();
    if (this.formulario.invalid) {
      return;
    }

    this.guardando.set(true);
    this.erroresCampo.set({});
    this.aviso.set(null);

    const v = this.formulario.getRawValue();
    const datos = {
      nombre: v.nombre.trim(),
      direccion: v.direccion.trim(),
      // `null` y no `''`: vacío pero informado no es lo mismo que sin dato.
      telefono: v.telefono.trim() || null,
      nit: v.nit.trim() || null,
      encabezado_recibo: v.encabezado_recibo.trim() || null,
      prefijo_comprobante: v.prefijo_comprobante.trim() || 'F',
    };

    const editando = this.editando();
    const peticion$ = editando
      ? this.sedesService.actualizar(editando.id, datos)
      : this.sedesService.crear(datos);

    peticion$.subscribe({
      next: () => {
        this.guardando.set(false);
        this.cerrarPanel();
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
          this.erroresCampo.set(error.error as ErroresDeCampo);
        } else {
          this.error.set('No se pudo guardar la sede.');
        }
      },
    });
  }

  protected cerrar(sede: SedeAdmin): void {
    if (!confirm(`¿Cerrar la sede "${sede.nombre}"? Dejará de poder venderse allí. Sus ventas, gastos y existencias se conservan.`)) {
      return;
    }

    this.ocupadoId.set(sede.id);
    this.error.set(null);
    this.aviso.set(null);

    this.sedesService.desactivar(sede.id).subscribe({
      next: (resultado) => {
        this.ocupadoId.set(null);
        // Quien solo trabajaba en esa sede se queda sin ninguna, y sin sede
        // no puede vender. Es un aviso, no un bloqueo: cerrar la sede es una
        // decisión legítima, pero no debe pasar en silencio.
        if (resultado.usuarios_sin_sede.length > 0) {
          this.aviso.set(
            `Estas personas se quedaron sin ninguna sede y no podrán vender hasta que ` +
              `les asignes otra: ${resultado.usuarios_sin_sede.join(', ')}.`,
          );
        }
        this.cargar();
      },
      error: (error: unknown) => {
        this.ocupadoId.set(null);
        this.error.set(this.mensaje(error, 'No se pudo cerrar la sede.'));
      },
    });
  }

  protected reabrir(sede: SedeAdmin): void {
    this.ocupadoId.set(sede.id);
    this.error.set(null);
    this.sedesService.activar(sede.id).subscribe({
      next: () => {
        this.ocupadoId.set(null);
        this.cargar();
      },
      error: () => {
        this.ocupadoId.set(null);
        this.error.set('No se pudo reabrir la sede.');
      },
    });
  }

  private mensaje(error: unknown, porDefecto: string): string {
    if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
      const cuerpo = error.error as Record<string, unknown>;
      if (typeof cuerpo['detail'] === 'string') {
        return cuerpo['detail'];
      }
    }
    return porDefecto;
  }

  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  protected descartarAviso(): void {
    this.aviso.set(null);
  }
}
