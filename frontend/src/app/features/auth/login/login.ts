import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { subdominioDesdeHostname } from '../../../core/tenant/subdominio.util';

/**
 * Pantalla de login (Parte A3). El campo "código de gimnasio" (subdominio)
 * solo se muestra si NO se pudo deducir del hostname actual (p. ej. entrando
 * por `localhost` a secas): si `subdominioDesdeHostname()` ya resolvió uno,
 * `AuthService.login` lo añade solo y no hace falta pedírselo al usuario.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class Login {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** Si es `null`, el hostname actual no trae subdominio de tenant y hay que pedirlo a mano. */
  protected readonly subdominioDeducido = subdominioDesdeHostname(window.location.hostname);
  protected readonly requiereCodigoGimnasio = this.subdominioDeducido === null;

  protected readonly enviando = signal(false);
  protected readonly errorBackend = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    // Obligatorio SOLO cuando el campo se muestra. Si el subdominio se dedujo
    // del hostname, el campo ni siquiera aparece y exigirlo dejaría el
    // formulario permanentemente inválido.
    subdominio: ['', this.requiereCodigoGimnasio ? [Validators.required] : []],
    correo: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  protected readonly puedeEnviar = computed(() => !this.enviando());

  onSubmit(): void {
    if (this.form.invalid || this.enviando()) {
      this.form.markAllAsTouched();
      return;
    }

    this.errorBackend.set(null);
    this.enviando.set(true);

    const { subdominio, correo, password } = this.form.getRawValue();

    this.authService
      .login({
        correo,
        password,
        ...(this.requiereCodigoGimnasio && subdominio ? { subdominio } : {}),
      })
      .subscribe({
        next: () => {
          this.enviando.set(false);
          const destino = this.route.snapshot.queryParamMap.get('redirect');
          this.router.navigateByUrl(destino || '/pos');
        },
        error: (error: unknown) => {
          this.enviando.set(false);
          this.errorBackend.set(this.extraerMensaje(error));
        },
      });
  }

  /** El backend ya devuelve mensajes en español listos para mostrar (ver
   * encargo): se muestran tal cual, sin traducirlos ni envolverlos en
   * "Error 400". */
  private extraerMensaje(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const cuerpo = error.error;
      if (cuerpo && typeof cuerpo === 'object') {
        if (typeof cuerpo.detail === 'string') {
          return cuerpo.detail;
        }
        const primerCampo = Object.values(cuerpo).find(
          (valor): valor is string[] => Array.isArray(valor) && valor.length > 0,
        );
        if (primerCampo) {
          return primerCampo[0];
        }
      }
      if (error.status === 0) {
        return 'No se pudo conectar con el servidor. Verifica tu conexión.';
      }
    }
    return 'Ocurrió un error inesperado. Inténtalo de nuevo.';
  }
}
