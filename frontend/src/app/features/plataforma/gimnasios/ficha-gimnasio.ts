import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { PlataformaService } from '../../../core/services/plataforma.service';
import {
  ETIQUETAS_ESTADO_TENANT,
  EstadoTenant,
  PasswordRestablecida,
  TenantDetalle,
  UsuarioDeGimnasio,
} from '../../../core/models/plataforma.model';

type ErroresDeCampo = Record<string, string | string[]>;

const CLASES_ESTADO: Record<EstadoTenant, string> = {
  prueba: 'bg-primary-container text-on-primary-container',
  activo: 'bg-success-bg text-success-text',
  mora: 'bg-warning-bg text-warning-text',
  suspendido: 'bg-danger-bg text-danger-text',
  cancelado: 'bg-surface-container-highest text-on-surface-variant',
};

/** Qué implica cada estado, en una frase. Se enseña ANTES de confirmar:
 * "suspendido" no dice por sí solo que echa a todo el mundo del gimnasio. */
const CONSECUENCIA_ESTADO: Record<EstadoTenant, string> = {
  prueba: 'El gimnasio sigue funcionando con normalidad.',
  activo: 'El gimnasio funciona con normalidad.',
  mora: 'El gimnasio sigue funcionando. Solo marca que tiene pagos pendientes.',
  suspendido:
    'Sus usuarios dejarán de poder entrar de inmediato. Los datos se conservan intactos.',
  cancelado:
    'Sus usuarios dejarán de poder entrar y se programará la eliminación de sus datos a 91 días.',
};

/** Estados que dejan al gimnasio fuera de servicio. */
const ESTADOS_QUE_EXPULSAN: EstadoTenant[] = ['suspendido', 'cancelado'];

@Component({
  selector: 'app-plataforma-ficha-gimnasio',
  imports: [ReactiveFormsModule],
  templateUrl: './ficha-gimnasio.html',
})
export class PlataformaFichaGimnasio {
  private readonly plataformaService = inject(PlataformaService);
  private readonly fb = inject(FormBuilder);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly gimnasio = signal<TenantDetalle | null>(null);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  /** Solo el rol `administrador` puede tocar nada: el backend responde 403 al
   * resto, y enseñar botones que van a fallar no ayuda a nadie. */
  protected readonly puedeGestionar = this.plataformaService.esAdministrador;

  protected readonly editando = signal(false);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly formulario = this.fb.nonNullable.group({
    nombre_comercial: ['', [Validators.required]],
    responsable: [''],
    correo: [''],
    telefono: [''],
    ciudad: [''],
    nit: [''],
    zona_horaria: ['', [Validators.required]],
    moneda: ['', [Validators.required]],
    dias_aviso_vencimiento: [5],
    minutos_antipassback: [60],
  });

  // --- Cambio de estado ---
  protected readonly cambiandoEstado = signal(false);
  protected readonly estadoElegido = signal<EstadoTenant | null>(null);
  protected readonly confirmacion = this.fb.nonNullable.control('');
  protected readonly errorEstado = signal<string | null>(null);

  protected readonly opcionesEstado: EstadoTenant[] = [
    'prueba', 'activo', 'mora', 'suspendido', 'cancelado',
  ];

  /** `true` si el estado elegido deja al gimnasio fuera de servicio: la
   * pantalla lo pinta en rojo y avisa antes de confirmar. */
  protected readonly esDestructivo = computed(() => {
    const estado = this.estadoElegido();
    return estado !== null && ESTADOS_QUE_EXPULSAN.includes(estado);
  });

  constructor() {
    const uuid = this.route.snapshot.paramMap.get('uuid');
    if (!uuid) {
      this.router.navigate(['/plataforma/gimnasios']);
      return;
    }
    this.cargar(uuid);
    this.cargarUsuarios(uuid);
  }

  private cargar(uuid: string): void {
    this.plataformaService.obtenerTenant(uuid).subscribe({
      next: (gimnasio) => {
        this.gimnasio.set(gimnasio);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudo cargar el gimnasio.');
      },
    });
  }

  // --- Edición ---------------------------------------------------------

  protected abrirEdicion(g: TenantDetalle): void {
    this.erroresCampo.set({});
    this.formulario.patchValue({
      nombre_comercial: g.nombre_comercial,
      responsable: g.responsable,
      correo: g.correo,
      telefono: g.telefono ?? '',
      ciudad: g.ciudad ?? '',
      nit: g.nit ?? '',
      zona_horaria: g.zona_horaria,
      moneda: g.moneda,
      dias_aviso_vencimiento: g.dias_aviso_vencimiento,
      minutos_antipassback: g.minutos_antipassback,
    });
    this.editando.set(true);
  }

  protected cancelarEdicion(): void {
    this.editando.set(false);
    this.erroresCampo.set({});
  }

  protected guardar(): void {
    const g = this.gimnasio();
    if (g === null || this.guardando() || this.formulario.invalid) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.guardando.set(true);
    this.erroresCampo.set({});

    const v = this.formulario.getRawValue();
    this.plataformaService
      .actualizarTenant(g.uuid_publico, {
        nombre_comercial: v.nombre_comercial.trim(),
        responsable: v.responsable.trim(),
        correo: v.correo.trim(),
        // Los opcionales van como `null` cuando se vacían: guardar `''`
        // dejaría un teléfono "vacío pero informado", que no es lo mismo.
        telefono: v.telefono.trim() || null,
        ciudad: v.ciudad.trim() || null,
        nit: v.nit.trim() || null,
        zona_horaria: v.zona_horaria.trim(),
        moneda: v.moneda.trim(),
        dias_aviso_vencimiento: v.dias_aviso_vencimiento,
        minutos_antipassback: v.minutos_antipassback,
      })
      .subscribe({
        next: (actualizado) => {
          this.guardando.set(false);
          this.editando.set(false);
          this.gimnasio.set(actualizado);
        },
        error: (error: unknown) => {
          this.guardando.set(false);
          if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
            this.erroresCampo.set(error.error as ErroresDeCampo);
          } else {
            this.error.set('No se pudo guardar.');
          }
        },
      });
  }

  protected errorDe(campo: string): string | null {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return null;
    }
    return Array.isArray(valor) ? valor.join(' ') : valor;
  }

  // --- Estado ----------------------------------------------------------

  protected elegirEstado(estado: EstadoTenant): void {
    this.estadoElegido.set(estado);
    this.confirmacion.setValue('');
    this.errorEstado.set(null);
  }

  protected cancelarCambioEstado(): void {
    this.estadoElegido.set(null);
    this.confirmacion.setValue('');
    this.errorEstado.set(null);
  }

  protected confirmarEstado(): void {
    const g = this.gimnasio();
    const estado = this.estadoElegido();
    if (g === null || estado === null || this.cambiandoEstado()) {
      return;
    }

    this.cambiandoEstado.set(true);
    this.errorEstado.set(null);

    this.plataformaService.cambiarEstado(g.uuid_publico, estado, this.confirmacion.value).subscribe({
      next: (actualizado) => {
        this.cambiandoEstado.set(false);
        this.gimnasio.set(actualizado);
        this.cancelarCambioEstado();
      },
      error: (error: unknown) => {
        this.cambiandoEstado.set(false);
        this.errorEstado.set(this.mensajeEstado(error));
      },
    });
  }

  private mensajeEstado(error: unknown): string {
    if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
      const cuerpo = error.error as Record<string, unknown>;
      for (const clave of ['confirmacion', 'estado', 'detail']) {
        const valor = cuerpo[clave];
        if (typeof valor === 'string') {
          return valor;
        }
        if (Array.isArray(valor) && typeof valor[0] === 'string') {
          return valor[0];
        }
      }
    }
    return 'No se pudo cambiar el estado.';
  }

  protected consecuenciaDe(estado: EstadoTenant): string {
    return CONSECUENCIA_ESTADO[estado];
  }

  // --- Usuarios y rescate de contraseña --------------------------------

  protected readonly usuarios = signal<UsuarioDeGimnasio[]>([]);
  protected readonly cargandoUsuarios = signal(false);

  /** Usuario cuyo restablecimiento se está confirmando. */
  protected readonly usuarioARestablecer = signal<UsuarioDeGimnasio | null>(null);
  protected readonly restableciendo = signal(false);
  /** Credencial recién generada. Se enseña una vez y no vuelve. */
  protected readonly passwordGenerada = signal<PasswordRestablecida | null>(null);
  protected readonly errorPassword = signal<string | null>(null);
  protected readonly copiadoPassword = signal(false);

  private cargarUsuarios(uuid: string): void {
    this.cargandoUsuarios.set(true);
    this.plataformaService.usuariosDe(uuid).subscribe({
      next: (usuarios) => {
        this.usuarios.set(usuarios);
        this.cargandoUsuarios.set(false);
      },
      error: () => {
        this.usuarios.set([]);
        this.cargandoUsuarios.set(false);
      },
    });
  }

  protected pedirRestablecer(usuario: UsuarioDeGimnasio): void {
    this.usuarioARestablecer.set(usuario);
    this.passwordGenerada.set(null);
    this.errorPassword.set(null);
  }

  protected cancelarRestablecer(): void {
    this.usuarioARestablecer.set(null);
    this.errorPassword.set(null);
  }

  protected confirmarRestablecer(): void {
    const g = this.gimnasio();
    const usuario = this.usuarioARestablecer();
    if (g === null || usuario === null || this.restableciendo()) {
      return;
    }

    this.restableciendo.set(true);
    this.errorPassword.set(null);

    this.plataformaService.restablecerPassword(g.uuid_publico, usuario.id).subscribe({
      next: (resultado) => {
        this.restableciendo.set(false);
        this.usuarioARestablecer.set(null);
        this.passwordGenerada.set(resultado);
      },
      error: (error: unknown) => {
        this.restableciendo.set(false);
        this.errorPassword.set(
          error instanceof HttpErrorResponse && error.status === 403
            ? 'Tu cuenta no tiene permiso para restablecer contraseñas.'
            : 'No se pudo restablecer la contraseña.',
        );
      },
    });
  }

  protected copiarPassword(dato: PasswordRestablecida): void {
    const texto = [
      `Gimnasio: ${dato.subdominio}`,
      `Usuario: ${dato.usuario.correo}`,
      `Contraseña: ${dato.password}`,
    ].join('\n');

    navigator.clipboard?.writeText(texto).then(
      () => {
        this.copiadoPassword.set(true);
        setTimeout(() => this.copiadoPassword.set(false), 2000);
      },
      () => this.errorPassword.set('No se pudo copiar. Anota la contraseña manualmente.'),
    );
  }

  protected descartarPassword(): void {
    this.passwordGenerada.set(null);
  }

  // --- Presentación ----------------------------------------------------

  protected volver(): void {
    this.router.navigate(['/plataforma/gimnasios']);
  }

  protected etiquetaEstado(estado: EstadoTenant): string {
    return ETIQUETAS_ESTADO_TENANT[estado];
  }

  protected claseEstado(estado: EstadoTenant): string {
    return `inline-block rounded-full px-2.5 py-1 text-sm font-medium ${CLASES_ESTADO[estado]}`;
  }

  protected numero(valor: number | null): string {
    return valor === null ? '—' : valor.toLocaleString('es-CO');
  }

  /** Fecha suelta (`YYYY-MM-DD`). Se le añade la hora para que el navegador
   * no la interprete en UTC y la retrase un día. */
  protected fecha(valor: string | null): string {
    if (!valor) {
      return '—';
    }
    const fecha = new Date(`${valor}T00:00:00`);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  /** Instante completo, al contrario que `fecha()`: aquí no hay que añadir
   * nada, la cadena ya trae la hora y la zona. */
  protected instante(valor: string | null): string {
    if (!valor) {
      return '—';
    }
    const fecha = new Date(valor);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleString('es-CO', {
          day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
        });
  }

  protected dinero(valor: string): string {
    const numero = Number(valor);
    return Number.isNaN(numero) ? valor : numero.toLocaleString('es-CO');
  }
}
