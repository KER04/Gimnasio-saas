import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { PlataformaService } from '../../../core/services/plataforma.service';

type ErroresDeCampo = Record<string, string | string[]>;

/** Mi cuenta del proveedor: quién soy y cambio de contraseña. */
@Component({
  selector: 'app-plataforma-cuenta',
  imports: [ReactiveFormsModule],
  templateUrl: './cuenta-plataforma.html',
})
export class PlataformaCuenta {
  private readonly plataformaService = inject(PlataformaService);
  private readonly fb = inject(FormBuilder);

  protected readonly usuario = this.plataformaService.usuario;

  /** Iniciales para el avatar del encabezado. Dos como mucho: con tres deja
   * de leerse dentro del círculo. */
  protected readonly iniciales = computed(() => {
    const nombre = this.usuario()?.nombre ?? '';
    return nombre
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((parte) => parte[0]?.toUpperCase() ?? '')
      .join('');
  });

  protected readonly guardando = signal(false);
  protected readonly exito = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});
  protected readonly verPassword = signal(false);

  protected readonly formulario = this.fb.nonNullable.group({
    password_actual: ['', [Validators.required]],
    password_nueva: ['', [Validators.required]],
    repetir: ['', [Validators.required]],
  });

  protected enviar(): void {
    if (this.guardando()) {
      return;
    }
    this.formulario.markAllAsTouched();
    if (this.formulario.invalid) {
      return;
    }

    const { password_actual, password_nueva, repetir } = this.formulario.getRawValue();
    if (password_nueva !== repetir) {
      this.erroresCampo.set({ repetir: 'Las dos contraseñas no coinciden.' });
      return;
    }

    this.guardando.set(true);
    this.exito.set(false);
    this.error.set(null);
    this.erroresCampo.set({});

    this.plataformaService.cambiarPassword(password_actual, password_nueva).subscribe({
      next: () => {
        this.guardando.set(false);
        this.exito.set(true);
        this.formulario.reset();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
          const cuerpo = error.error as Record<string, unknown>;
          if (typeof cuerpo['detail'] === 'string') {
            this.error.set(cuerpo['detail']);
            return;
          }
          this.erroresCampo.set(cuerpo as ErroresDeCampo);
          return;
        }
        this.error.set('No se pudo cambiar la contraseña.');
      },
    });
  }

  /** Django devuelve varios motivos a la vez; se enseñan todos. */
  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }
}
