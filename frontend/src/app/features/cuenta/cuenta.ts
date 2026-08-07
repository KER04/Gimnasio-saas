import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { AuthService } from '../../core/services/auth.service';

type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Mi cuenta: datos de la sesión y cambio de contraseña.
 *
 * Es de solo lectura salvo la contraseña. Editar el propio nombre, correo o
 * rol es gestión de usuarios, que hoy no existe como pantalla y tiene sus
 * propias reglas (nadie debería poder cambiarse el rol a sí mismo).
 */
@Component({
  selector: 'app-cuenta',
  imports: [ReactiveFormsModule],
  templateUrl: './cuenta.html',
})
export class MiCuenta {
  private readonly authService = inject(AuthService);
  private readonly fb = inject(FormBuilder);

  protected readonly sesion = this.authService.sesion;
  protected readonly nombreRol = this.authService.nombreRol;
  protected readonly nombreSede = computed(() => this.authService.sedeActual()?.nombre ?? null);

  /** Iniciales para el avatar del encabezado. Dos como mucho: con tres deja
   * de leerse dentro del círculo. */
  protected readonly iniciales = computed(() => {
    const nombre = this.sesion()?.nombre ?? '';
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

    // Se comprueba aquí y no en el backend: la repetición existe para
    // detectar erratas al teclear, no es un dato que el servidor necesite.
    if (password_nueva !== repetir) {
      this.erroresCampo.set({ repetir: 'Las dos contraseñas no coinciden.' });
      return;
    }

    this.guardando.set(true);
    this.exito.set(false);
    this.error.set(null);
    this.erroresCampo.set({});

    this.authService.cambiarPassword(password_actual, password_nueva).subscribe({
      next: () => {
        this.guardando.set(false);
        this.exito.set(true);
        this.formulario.reset();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        this.procesarError(error);
      },
    });
  }

  private procesarError(error: unknown): void {
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
  }

  /** Los validadores de Django devuelven VARIOS motivos a la vez ("demasiado
   * corta", "demasiado común"…). Se enseñan todos: corregir uno y volver a
   * fallar por el siguiente es la peor forma de descubrirlos. */
  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }
}
