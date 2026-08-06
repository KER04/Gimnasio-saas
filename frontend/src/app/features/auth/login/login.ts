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

  /** Mostrar la contraseña en claro. Ayuda de verdad en un mostrador, donde
   * se teclea rápido y a menudo con el móvil. */
  protected readonly passwordVisible = signal(false);

  /**
   * Crédito del pie. Vive aquí y no en la plantilla porque aparece DOS veces
   * —en el panel morado de escritorio y en el pie de móvil, que se excluyen
   * entre sí—, y tenerlo duplicado hacía que cambiar uno pareciera no surtir
   * efecto: se editaba el que estaba oculto en ese tamaño de pantalla.
   */
  protected readonly desarrolladoPor = 'KEVINGOOOD';

  protected alternarPassword(): void {
    this.passwordVisible.update((visible) => !visible);
  }

  /**
   * Lo que se promete en el panel izquierdo. Se declara aquí, y no suelto en
   * la plantilla, para que quede claro que cada punto describe algo que la
   * aplicación HACE -- nada de "cifrado de nivel bancario" ni promesas de
   * marketing que nadie pueda comprobar.
   */
  protected readonly caracteristicas = [
    {
      icono: 'shield_lock',
      titulo: 'Datos aislados',
      texto: 'Cada gimnasio ve solo lo suyo. El aislamiento lo impone la base de datos, no la aplicación.',
    },
    {
      icono: 'payments',
      titulo: 'Caja cuadrada',
      texto: 'Ventas, abonos y cartera al día, con el corte diario desglosado por forma de pago.',
    },
    {
      icono: 'fact_check',
      titulo: 'Acceso y stock',
      texto: 'Vencimientos avisados a tiempo, control de entrada e inventario con su libro de movimientos.',
    },
  ];

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
