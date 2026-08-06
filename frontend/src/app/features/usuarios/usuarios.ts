import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Observable, forkJoin } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { SedesService } from '../../core/services/sedes.service';
import { UsuariosService } from '../../core/services/usuarios.service';
import { SedeOrganizacion } from '../../core/models/sede.model';
import {
  RolGimnasio,
  UsuarioConPassword,
  UsuarioGimnasio,
} from '../../core/models/usuario.model';

type ErroresDeCampo = Record<string, string | string[]>;

/**
 * Personal del gimnasio.
 *
 * Un usuario no se borra nunca: sus ventas, cobros y movimientos de
 * inventario lo protegen en la base de datos, y un recibo tiene que poder
 * decir quién lo hizo aunque esa persona ya no trabaje allí. Aquí se da de
 * baja, que le quita el acceso y conserva el histórico.
 */
@Component({
  selector: 'app-usuarios',
  imports: [ReactiveFormsModule],
  templateUrl: './usuarios.html',
})
export class UsuariosGestion {
  private readonly usuariosService = inject(UsuariosService);
  private readonly sedesService = inject(SedesService);
  private readonly authService = inject(AuthService);
  private readonly fb = inject(FormBuilder);

  protected readonly usuarios = signal<UsuarioGimnasio[]>([]);
  protected readonly roles = signal<RolGimnasio[]>([]);
  protected readonly sedes = signal<SedeOrganizacion[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly verInactivos = signal(false);

  /** Quién soy: la pantalla no ofrece acciones que el backend va a rechazar
   * por ser sobre uno mismo (desactivarse, cambiarse el rol). */
  protected readonly miId = computed(() => this.authService.sesion()?.id ?? null);

  protected readonly panelAbierto = signal(false);
  protected readonly usuarioEditando = signal<UsuarioGimnasio | null>(null);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  /** Credencial recién generada, del alta o de un restablecimiento. Se
   * enseña una vez y no vuelve. */
  protected readonly credencial = signal<UsuarioConPassword | null>(null);
  protected readonly copiado = signal(false);
  protected readonly ocupadoId = signal<number | null>(null);

  protected readonly formulario = this.fb.nonNullable.group({
    nombre: ['', [Validators.required]],
    correo: ['', [Validators.required, Validators.email]],
    telefono: [''],
    rol: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    sedes: this.fb.nonNullable.control<number[]>([]),
  });

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    forkJoin({
      usuarios: this.usuariosService.listar(this.verInactivos()),
      roles: this.usuariosService.listarRoles(),
      sedes: this.sedesService.listar(),
    }).subscribe({
      next: ({ usuarios, roles, sedes }) => {
        this.usuarios.set(usuarios);
        this.roles.set(roles);
        this.sedes.set(sedes);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar los usuarios.');
      },
    });
  }

  protected alternarInactivos(): void {
    this.verInactivos.update((valor) => !valor);
    this.cargar();
  }

  // --- Alta y edición --------------------------------------------------

  protected abrirAlta(): void {
    this.usuarioEditando.set(null);
    this.erroresCampo.set({});
    this.credencial.set(null);
    this.formulario.reset({ rol: '', sedes: [] });
    this.formulario.controls.correo.enable();
    this.panelAbierto.set(true);
  }

  protected abrirEdicion(usuario: UsuarioGimnasio): void {
    this.usuarioEditando.set(usuario);
    this.erroresCampo.set({});
    this.credencial.set(null);
    this.formulario.reset({
      nombre: usuario.nombre,
      correo: usuario.correo,
      telefono: usuario.telefono ?? '',
      rol: usuario.rol,
      sedes: usuario.sedes.map((s) => s.id),
    });
    // El correo es la credencial de acceso: no se edita.
    this.formulario.controls.correo.disable();
    this.panelAbierto.set(true);
  }

  protected cerrarPanel(): void {
    this.panelAbierto.set(false);
    this.usuarioEditando.set(null);
    this.erroresCampo.set({});
  }

  protected alternarSede(sedeId: number): void {
    const control = this.formulario.controls.sedes;
    const actuales = control.value;
    control.setValue(
      actuales.includes(sedeId)
        ? actuales.filter((id) => id !== sedeId)
        : [...actuales, sedeId],
    );
  }

  protected tieneSede(sedeId: number): boolean {
    return this.formulario.controls.sedes.value.includes(sedeId);
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

    const v = this.formulario.getRawValue();
    const editando = this.usuarioEditando();

    if (editando) {
      this.usuariosService
        .actualizar(editando.id, {
          nombre: v.nombre.trim(),
          telefono: v.telefono.trim() || null,
          rol: v.rol as number,
          sedes: v.sedes,
        })
        .subscribe({
          next: () => {
            this.guardando.set(false);
            this.cerrarPanel();
            this.cargar();
          },
          error: (error: unknown) => this.fallo(error),
        });
      return;
    }

    this.usuariosService
      .crear({
        nombre: v.nombre.trim(),
        correo: v.correo.trim().toLowerCase(),
        telefono: v.telefono.trim() || undefined,
        rol: v.rol as number,
        sedes: v.sedes,
      })
      .subscribe({
        next: (creado) => {
          this.guardando.set(false);
          this.cerrarPanel();
          // La contraseña solo existe aquí: la pantalla se queda
          // enseñándola en vez de volver al listado sin más.
          this.credencial.set(creado);
          this.cargar();
        },
        error: (error: unknown) => this.fallo(error),
      });
  }

  private fallo(error: unknown): void {
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
    this.error.set('No se pudo guardar.');
  }

  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  // --- Acciones sobre la fila ------------------------------------------

  protected desactivar(usuario: UsuarioGimnasio): void {
    if (!confirm(`¿Quitarle el acceso a ${usuario.nombre}? Sus ventas y cobros anteriores se conservan intactos.`)) {
      return;
    }
    this.ejecutar(usuario, this.usuariosService.desactivar(usuario.id));
  }

  protected activar(usuario: UsuarioGimnasio): void {
    this.ejecutar(usuario, this.usuariosService.activar(usuario.id));
  }

  protected restablecer(usuario: UsuarioGimnasio): void {
    if (!confirm(`¿Generar una contraseña nueva para ${usuario.nombre}? La actual dejará de servir y se cerrarán sus sesiones abiertas.`)) {
      return;
    }
    this.ocupadoId.set(usuario.id);
    this.error.set(null);
    this.usuariosService.restablecerPassword(usuario.id).subscribe({
      next: (resultado) => {
        this.ocupadoId.set(null);
        this.credencial.set(resultado);
      },
      error: (error: unknown) => {
        this.ocupadoId.set(null);
        this.error.set(this.mensaje(error, 'No se pudo restablecer la contraseña.'));
      },
    });
  }

  private ejecutar(usuario: UsuarioGimnasio, peticion$: Observable<UsuarioGimnasio>): void {
    this.ocupadoId.set(usuario.id);
    this.error.set(null);
    peticion$.subscribe({
      next: () => {
        this.ocupadoId.set(null);
        this.cargar();
      },
      error: (error: unknown) => {
        this.ocupadoId.set(null);
        this.error.set(this.mensaje(error, 'No se pudo completar la acción.'));
      },
    });
  }

  private mensaje(error: unknown, porDefecto: string): string {
    if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
      const cuerpo = error.error as Record<string, unknown>;
      for (const valor of Object.values(cuerpo)) {
        if (typeof valor === 'string') {
          return valor;
        }
        if (Array.isArray(valor) && typeof valor[0] === 'string') {
          return valor[0];
        }
      }
    }
    return porDefecto;
  }

  // --- Credencial ------------------------------------------------------

  protected copiar(credencial: UsuarioConPassword): void {
    const texto = [
      `Usuario: ${credencial.correo}`,
      `Contraseña: ${credencial.password}`,
    ].join('\n');

    navigator.clipboard?.writeText(texto).then(
      () => {
        this.copiado.set(true);
        setTimeout(() => this.copiado.set(false), 2000);
      },
      () => this.error.set('No se pudo copiar. Anota la contraseña manualmente.'),
    );
  }

  protected descartarCredencial(): void {
    this.credencial.set(null);
  }

  protected esUnoMismo(usuario: UsuarioGimnasio): boolean {
    return usuario.id === this.miId();
  }

  protected sedesTexto(usuario: UsuarioGimnasio): string {
    if (usuario.sedes.length === 0) {
      return 'Sin sede asignada';
    }
    return usuario.sedes.map((s) => s.nombre).join(', ');
  }

  protected ultimoAcceso(valor: string | null): string {
    if (!valor) {
      return 'Nunca ha entrado';
    }
    const fecha = new Date(valor);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }
}
