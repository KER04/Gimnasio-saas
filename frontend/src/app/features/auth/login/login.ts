import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../../../core/services/auth.service';
import { TenantService } from '../../../core/tenant/tenant.service';

/**
 * Pantalla de login. Fuera del layout principal a propósito (ver
 * `app.routes.ts`): no lleva header/aside/footer.
 *
 * El campo "código de gimnasio" solo aparece cuando el subdominio no se pudo
 * deducir de la URL (p. ej. entrando por `localhost` en desarrollo). Si ya
 * se dedujo, preguntarlo sería pedir algo que ya sabemos.
 */
@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule],
  templateUrl: './login.html',
  styleUrl: './login.css',
})
export class Login {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  protected readonly tenantService = inject(TenantService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** `true` cuando hay que pedir el código de gimnasio a mano. */
  protected readonly requiereCodigoGimnasio = computed(() => !this.tenantService.seDeduceDeLaUrl());

  protected readonly enviando = signal(false);
  protected readonly errorBackend = signal<string | null>(null);

  protected readonly form = this.fb.nonNullable.group({
    codigoGimnasio: this.fb.nonNullable.control(''),
    correo: this.fb.nonNullable.control('', [Validators.required, Validators.email]),
    password: this.fb.nonNullable.control('', [Validators.required]),
  });

  constructor() {
    // El código de gimnasio solo es obligatorio cuando se muestra. Se fija
    // aquí (no en el binding del template) para que Angular valide el
    // formulario completo con la regla correcta antes de enviar.
    if (this.requiereCodigoGimnasio()) {
      this.form.controls.codigoGimnasio.addValidators(Validators.required);
      this.form.controls.codigoGimnasio.updateValueAndValidity();
    }
  }

  protected enviar(): void {
    if (this.enviando()) {
      return;
    }

    this.form.markAllAsTouched();
    if (this.form.invalid) {
      return;
    }

    this.errorBackend.set(null);
    this.enviando.set(true);

    const { codigoGimnasio, correo, password } = this.form.getRawValue();
    const subdominio = this.requiereCodigoGimnasio() ? codigoGimnasio.trim() : undefined;

    this.authService.login({ subdominio, correo, password }).subscribe({
      next: () => {
        if (subdominio) {
          this.tenantService.establecer(subdominio);
        }
        this.enviando.set(false);
        const destino = this.route.snapshot.queryParamMap.get('redirigirA') ?? '/dashboard';
        this.router.navigateByUrl(destino);
      },
      error: (error: unknown) => {
        this.enviando.set(false);
        this.errorBackend.set(this.mensajeDeError(error));
      },
    });
  }

  private mensajeDeError(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo iniciar sesión. Inténtalo de nuevo.';
  }
}
