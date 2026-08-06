import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { PlataformaService } from '../../../core/services/plataforma.service';
import { AccesoInicial, TenantCreado } from '../../../core/models/plataforma.model';

type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Alta de un gimnasio.
 *
 * El alta crea mucho más que una fila: sede, roles, permisos, semillas y el
 * usuario administrador. Por eso, al terminar, la pantalla no vuelve al
 * listado sino que se queda enseñando las credenciales: la contraseña la
 * genera el servidor y es la ÚNICA vez que se puede leer.
 */
@Component({
  selector: 'app-plataforma-nuevo-gimnasio',
  imports: [ReactiveFormsModule],
  templateUrl: './nuevo-gimnasio.html',
})
export class PlataformaNuevoGimnasio {
  private readonly fb = inject(FormBuilder);
  private readonly plataformaService = inject(PlataformaService);
  private readonly router = inject(Router);

  protected readonly enviando = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  /** Cuando deja de ser `null`, el alta terminó y la pantalla pasa a enseñar
   * las credenciales en vez del formulario. */
  protected readonly creado = signal<TenantCreado | null>(null);
  protected readonly copiado = signal(false);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre_comercial: ['', [Validators.required]],
    // Vacío = se propone a partir del nombre. Una vez creado no se puede
    // cambiar, así que conviene decirlo en la propia pantalla.
    subdominio: [''],
    correo_admin: ['', [Validators.required, Validators.email]],
    nombre_sede: [''],
    responsable: [''],
    telefono: [''],
    ciudad: [''],
    nit: [''],
  });

  protected enviar(): void {
    if (this.enviando() || this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.enviando.set(true);
    this.error.set(null);
    this.erroresCampo.set({});

    const valores = this.formulario.getRawValue();
    // Los opcionales vacíos NO se mandan: `''` y "no informado" no son lo
    // mismo, y el backend guardaría cadenas vacías donde debería ir null.
    const datos = Object.fromEntries(
      Object.entries(valores)
        .map(([clave, valor]) => [clave, typeof valor === 'string' ? valor.trim() : valor])
        .filter(([, valor]) => valor !== ''),
    ) as { nombre_comercial: string; correo_admin: string };

    this.plataformaService.crearTenant(datos).subscribe({
      next: (creado) => {
        this.enviando.set(false);
        this.creado.set(creado);
      },
      error: (error: unknown) => {
        this.enviando.set(false);
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
      this.error.set('Revisa los campos marcados.');
      return;
    }
    this.error.set('No se pudo crear el gimnasio.');
  }

  protected errorDe(campo: string): string | null {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return null;
    }
    return Array.isArray(valor) ? valor.join(' ') : valor;
  }

  /** Copia las credenciales al portapapeles de una vez: es lo que se le va a
   * pasar al cliente, y transcribir una contraseña de 16 caracteres a mano es
   * pedir una errata. */
  protected copiar(acceso: AccesoInicial): void {
    const texto = [
      `Gimnasio: ${acceso.url}`,
      `Usuario: ${acceso.correo}`,
      `Contraseña: ${acceso.password}`,
    ].join('\n');

    navigator.clipboard?.writeText(texto).then(
      () => {
        this.copiado.set(true);
        setTimeout(() => this.copiado.set(false), 2000);
      },
      () => {
        // El portapapeles puede estar bloqueado (permisos, http sin TLS).
        // No es un fallo del alta: la contraseña sigue a la vista.
        this.error.set('No se pudo copiar. Anota la contraseña manualmente.');
      },
    );
  }

  protected irAlGimnasio(creado: TenantCreado): void {
    this.router.navigate(['/plataforma/gimnasios', creado.uuid_publico]);
  }

  protected volver(): void {
    this.router.navigate(['/plataforma/gimnasios']);
  }
}
