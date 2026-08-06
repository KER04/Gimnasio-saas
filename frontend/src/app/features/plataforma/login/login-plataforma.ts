import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { PlataformaService } from '../../../core/services/plataforma.service';

/**
 * Acceso al panel del proveedor.
 *
 * Deliberadamente sobrio y distinto del login del gimnasio: quien llega aquí
 * no es un cliente, y la pantalla debe dejar claro de un vistazo que esto
 * gobierna TODOS los gimnasios. No pide código de gimnasio —no pertenece a
 * ninguno— ni ofrece registro: las cuentas se crean por consola
 * (`crear_usuario_plataforma`), que es la barrera que se busca.
 */
@Component({
  selector: 'app-login-plataforma',
  imports: [ReactiveFormsModule],
  templateUrl: './login-plataforma.html',
})
export class LoginPlataforma {
  private readonly fb = inject(FormBuilder);
  private readonly plataformaService = inject(PlataformaService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly enviando = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly passwordVisible = signal(false);

  protected readonly formulario = this.fb.nonNullable.group({
    correo: ['', [Validators.required]],
    password: ['', [Validators.required]],
  });

  protected alternarPassword(): void {
    this.passwordVisible.update((visible) => !visible);
  }

  protected enviar(): void {
    if (this.enviando() || this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.enviando.set(true);
    this.error.set(null);

    const { correo, password } = this.formulario.getRawValue();
    this.plataformaService.login(correo.trim(), password).subscribe({
      next: () => {
        this.enviando.set(false);
        const destino = this.route.snapshot.queryParamMap.get('redirigirA');
        this.router.navigateByUrl(destino || '/plataforma/gimnasios');
      },
      error: (error: unknown) => {
        this.enviando.set(false);
        this.error.set(this.mensaje(error));
      },
    });
  }

  private mensaje(error: unknown): string {
    if (error instanceof HttpErrorResponse) {
      if (error.status === 401) {
        // El backend ya devuelve el mismo texto para "no existe" y
        // "contraseña mala", a propósito. Se repite tal cual.
        return 'Correo o contraseña incorrectos.';
      }
      if (error.status === 0) {
        return 'No se pudo conectar con el servidor.';
      }
      const detalle = (error.error as { detail?: string } | null)?.detail;
      if (detalle) {
        return detalle;
      }
    }
    return 'No se pudo iniciar sesión.';
  }
}
