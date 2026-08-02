import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ClientesService } from '../../../core/services/clientes.service';
import { SedesService } from '../../../core/services/sedes.service';
import { Sexo } from '../../../core/models/cliente.model';
import { SedeOrganizacion } from '../../../core/models/sede.model';

/** Errores de campo tal como los devuelve DRF: `{"campo": "texto" | ["texto", ...]}`. */
type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Alta y edición de clientes (RF-03). Misma pantalla para `/clientes/nuevo`
 * y `/clientes/{id}/editar`: en edición se precarga la ficha y se ocultan
 * las autorizaciones (Ley 1581), que solo se registran al crear.
 */
@Component({
  selector: 'app-clientes-formulario',
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './formulario.html',
})
export class ClientesFormulario {
  private readonly fb = inject(FormBuilder);
  private readonly clientesService = inject(ClientesService);
  private readonly sedesService = inject(SedesService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  private readonly idParam = this.route.snapshot.paramMap.get('id');
  protected readonly clienteId = this.idParam ? Number(this.idParam) : null;
  protected readonly esEdicion = this.clienteId !== null;

  protected readonly sedes = signal<SedeOrganizacion[]>([]);
  protected readonly cargandoFicha = signal(this.esEdicion);
  protected readonly enviando = signal(false);
  protected readonly errorGeneral = signal<string | null>(null);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly titulo = computed(() => (this.esEdicion ? 'Editar cliente' : 'Nuevo cliente'));

  protected readonly form = this.fb.nonNullable.group({
    nombre: this.fb.nonNullable.control('', [Validators.required]),
    cedula: this.fb.nonNullable.control('', [Validators.required]),
    telefono: this.fb.nonNullable.control('', [Validators.required]),
    direccion: this.fb.nonNullable.control('', [Validators.required]),
    sexo: this.fb.nonNullable.control<Sexo | ''>(''),
    sede_origen: this.fb.nonNullable.control<number | ''>(''),
    autoriza_tratamiento_datos: this.fb.nonNullable.control(false),
    autoriza_biometria: this.fb.nonNullable.control(false),
  });

  constructor() {
    this.sedesService.listar().subscribe({
      next: (sedes) => this.sedes.set(sedes),
      error: () => this.sedes.set([]),
    });

    if (this.clienteId !== null) {
      this.clientesService.obtener(this.clienteId).subscribe({
        next: (cliente) => {
          this.form.patchValue({
            nombre: cliente.nombre,
            cedula: cliente.cedula,
            telefono: cliente.telefono,
            direccion: cliente.direccion,
            sexo: cliente.sexo ?? '',
            sede_origen: cliente.sede_origen,
          });
          this.cargandoFicha.set(false);
        },
        error: (error: unknown) => {
          this.cargandoFicha.set(false);
          this.errorGeneral.set(this.mensajeGeneral(error));
        },
      });
    }
  }

  protected errorDe(campo: string): string | null {
    const valor = this.erroresCampo()[campo];
    if (!valor) {
      return null;
    }
    return Array.isArray(valor) ? valor[0] : valor;
  }

  protected enviar(): void {
    if (this.enviando()) {
      return;
    }

    this.form.markAllAsTouched();
    if (this.form.invalid) {
      return;
    }

    this.errorGeneral.set(null);
    this.erroresCampo.set({});
    this.enviando.set(true);

    const valores = this.form.getRawValue();
    const payload = {
      nombre: valores.nombre.trim(),
      cedula: valores.cedula.trim(),
      telefono: valores.telefono.trim(),
      direccion: valores.direccion.trim(),
      sexo: valores.sexo || null,
      // La sede es opcional: si no se elige, se OMITE del cuerpo en vez de
      // mandarla en `null`. El backend deduce entonces la sede del usuario.
      // (También acepta `null`, pero omitirla expresa mejor "no la indico" y
      // deja el cuerpo más limpio.)
      ...(valores.sede_origen === '' ? {} : { sede_origen: valores.sede_origen }),
      ...(this.esEdicion
        ? {}
        : {
            autoriza_tratamiento_datos: valores.autoriza_tratamiento_datos,
            autoriza_biometria: valores.autoriza_biometria,
          }),
    };

    const peticion$ = this.esEdicion
      ? this.clientesService.actualizar(this.clienteId!, payload)
      : this.clientesService.crear(payload);

    peticion$.subscribe({
      next: (cliente) => {
        this.enviando.set(false);
        this.router.navigate(['/clientes', cliente.id]);
      },
      error: (error: unknown) => {
        this.enviando.set(false);
        this.manejarError(error);
      },
    });
  }

  private manejarError(error: unknown): void {
    if (error instanceof HttpErrorResponse && error.status === 400 && error.error) {
      const cuerpo = error.error as Record<string, unknown>;
      if (cuerpo['detail']) {
        this.errorGeneral.set(String(cuerpo['detail']));
        return;
      }
      // Diccionario de errores por campo (p. ej. cédula duplicada): se
      // muestran tal cual, en español, debajo de cada campo.
      this.erroresCampo.set(cuerpo as ErroresDeCampo);
      return;
    }
    this.errorGeneral.set(this.mensajeGeneral(error));
  }

  private mensajeGeneral(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo guardar el cliente. Inténtalo de nuevo.';
  }
}
