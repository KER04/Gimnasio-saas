import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, map, tap } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  EstadoTenant,
  Cobros,
  FacturaSuscripcion,
  PasswordRestablecida,
  PlanSuscripcion,
  PlanSuscripcionFormulario,
  RespuestaLoginPlataforma,
  SuscripcionDetalle,
  SuscripcionFormulario,
  TenantConfiguracion,
  TenantCreado,
  TenantDetalle,
  TenantNuevo,
  TenantResumen,
  UsuarioDeGimnasio,
  UsuarioPlataforma,
} from '../models/plataforma.model';
import { RespuestaPaginada } from '../models/paginacion.model';

/**
 * Claves de almacenamiento DISTINTAS de las del gimnasio
 * (`gimnasio_access`/`gimnasio_refresh`).
 *
 * No es cosmético: si compartieran clave, entrar al panel cerraría la sesión
 * del gimnasio abierta en la misma pestaña y —peor— el interceptor mandaría
 * el token equivocado a cada API. Separadas, las dos sesiones conviven.
 */
const CLAVE_ACCESS = 'plataforma_access';
const CLAVE_REFRESH = 'plataforma_refresh';

/** Prefijo que distingue las llamadas del panel. Lo usa el interceptor para
 * decidir qué token adjuntar. */
export const PREFIJO_API_PLATAFORMA = '/api/plataforma/';

@Injectable({ providedIn: 'root' })
export class PlataformaService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/plataforma`;

  private readonly usuarioSignal = signal<UsuarioPlataforma | null>(null);

  readonly usuario = this.usuarioSignal.asReadonly();
  readonly esAdministrador = computed(() => this.usuarioSignal()?.rol === 'administrador');

  login(correo: string, password: string): Observable<RespuestaLoginPlataforma> {
    return this.http
      .post<RespuestaLoginPlataforma>(`${this.base}/login/`, { correo, password })
      .pipe(
        tap((respuesta) => {
          this.guardarTokens(respuesta.access, respuesta.refresh);
          this.usuarioSignal.set(respuesta.usuario);
        }),
      );
  }

  /** Repuebla la sesión al recargar la página: los tokens sobreviven en
   * `localStorage`, el usuario no. */
  cargarUsuario(): Observable<UsuarioPlataforma> {
    return this.http
      .get<UsuarioPlataforma>(`${this.base}/me/`)
      .pipe(tap((usuario) => this.usuarioSignal.set(usuario)));
  }

  refrescar(): Observable<{ access: string }> {
    const refresh = this.obtenerRefreshToken();
    if (!refresh) {
      // Mismo criterio que el servicio del gimnasio: sin refresh no hay nada
      // que intentar, y devolver un observable que falla evita un 401 más.
      return new Observable((observador) => observador.error(new Error('Sin sesión de plataforma.')));
    }
    return this.http.post<{ access: string }>(`${this.base}/refresh/`, { refresh }).pipe(
      tap(({ access }) => this.guardarAccess(access)),
    );
  }

  cerrarSesion(): void {
    this.usuarioSignal.set(null);
    try {
      localStorage.removeItem(CLAVE_ACCESS);
      localStorage.removeItem(CLAVE_REFRESH);
    } catch {
      // localStorage puede estar bloqueado (modo privado, políticas del
      // navegador). Perder el borrado no debe romper el cierre de sesión:
      // el signal ya quedó vacío.
    }
  }

  estaAutenticado(): boolean {
    return this.obtenerAccessToken() !== null;
  }

  obtenerAccessToken(): string | null {
    try {
      return localStorage.getItem(CLAVE_ACCESS);
    } catch {
      return null;
    }
  }

  obtenerRefreshToken(): string | null {
    try {
      return localStorage.getItem(CLAVE_REFRESH);
    } catch {
      return null;
    }
  }

  private guardarTokens(access: string, refresh: string): void {
    try {
      localStorage.setItem(CLAVE_ACCESS, access);
      localStorage.setItem(CLAVE_REFRESH, refresh);
    } catch {
      // Ver cerrarSesion(): sin almacenamiento la sesión dura lo que la
      // pestaña, que es preferible a no dejar entrar.
    }
  }

  private guardarAccess(access: string): void {
    try {
      localStorage.setItem(CLAVE_ACCESS, access);
    } catch {
      // Ídem.
    }
  }

  // --- Gimnasios -------------------------------------------------------

  listarTenants(filtros: { buscar?: string; estado?: EstadoTenant | ''; page?: number } = {}):
    Observable<RespuestaPaginada<TenantResumen>> {
    let params = new HttpParams();
    if (filtros.buscar) {
      params = params.set('buscar', filtros.buscar);
    }
    if (filtros.estado) {
      params = params.set('estado', filtros.estado);
    }
    if (filtros.page) {
      params = params.set('page', filtros.page);
    }
    return this.http.get<RespuestaPaginada<TenantResumen>>(`${this.base}/tenants/`, { params });
  }

  obtenerTenant(uuid: string): Observable<TenantDetalle> {
    return this.http.get<TenantDetalle>(`${this.base}/tenants/${uuid}/`);
  }

  /**
   * Cambia la contraseña de la cuenta del proveedor.
   *
   * Los tokens anteriores dejan de valer en cuanto cambia la contraseña
   * (llevan una huella del hash), así que hay que guardar la pareja nueva o
   * la siguiente petición devolvería 401 y cerraría la sesión.
   */
  cambiarPassword(passwordActual: string, passwordNueva: string): Observable<void> {
    return this.http
      .post<{ access: string; refresh: string }>(`${this.base}/cambiar-password/`, {
        password_actual: passwordActual,
        password_nueva: passwordNueva,
      })
      .pipe(
        tap((respuesta) => this.guardarTokens(respuesta.access, respuesta.refresh)),
        map(() => undefined),
      );
  }

  // --- Planes de suscripción (el catálogo que vendes) ---

  listarPlanes(incluirInactivos = false): Observable<PlanSuscripcion[]> {
    const params = incluirInactivos
      ? new HttpParams().set('incluir_inactivos', '1')
      : undefined;
    return this.http
      .get<RespuestaPaginada<PlanSuscripcion>>(`${this.base}/planes-suscripcion/`, { params })
      .pipe(map((respuesta) => respuesta.results));
  }

  crearPlan(datos: PlanSuscripcionFormulario): Observable<PlanSuscripcion> {
    return this.http.post<PlanSuscripcion>(`${this.base}/planes-suscripcion/`, datos);
  }

  actualizarPlan(
    id: number,
    datos: Partial<PlanSuscripcionFormulario>,
  ): Observable<PlanSuscripcion> {
    return this.http.patch<PlanSuscripcion>(`${this.base}/planes-suscripcion/${id}/`, datos);
  }

  /** Baja LÓGICA: `Suscripcion.plan_suscripcion` es PROTECT y el histórico de
   * facturación tiene que poder explicarse entero. */
  darDeBajaPlan(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/planes-suscripcion/${id}/`);
  }

  // --- Suscripción de un gimnasio ---

  /** `null` si el gimnasio no tiene ningún contrato vivo. */
  obtenerSuscripcion(uuid: string): Observable<SuscripcionDetalle | null> {
    return this.http.get<SuscripcionDetalle | null>(`${this.base}/tenants/${uuid}/suscripcion/`);
  }

  /** Contrata un plan o cambia el actual. Cambiarlo cierra la suscripción
   * anterior y abre una nueva: solo puede haber una vigente. */
  contratarPlan(uuid: string, datos: SuscripcionFormulario): Observable<SuscripcionDetalle> {
    return this.http.post<SuscripcionDetalle>(`${this.base}/tenants/${uuid}/suscripcion/`, datos);
  }

  /** Termina el contrato. NO apaga el gimnasio: eso tiene su propia acción. */
  cancelarSuscripcion(uuid: string): Observable<SuscripcionDetalle> {
    return this.http.post<SuscripcionDetalle>(
      `${this.base}/tenants/${uuid}/cancelar-suscripcion/`, {},
    );
  }

  // --- Facturas ---

  emitirFactura(uuid: string): Observable<FacturaSuscripcion> {
    return this.http.post<FacturaSuscripcion>(`${this.base}/tenants/${uuid}/emitir-factura/`, {});
  }

  pagarFactura(uuid: string, facturaId: number): Observable<FacturaSuscripcion> {
    return this.http.post<FacturaSuscripcion>(
      `${this.base}/tenants/${uuid}/facturas/${facturaId}/pagar/`, {},
    );
  }

  anularFactura(uuid: string, facturaId: number): Observable<FacturaSuscripcion> {
    return this.http.post<FacturaSuscripcion>(
      `${this.base}/tenants/${uuid}/facturas/${facturaId}/anular/`, {},
    );
  }

  /** Quién te debe dinero. Sin rango de fechas a propósito: una deuda no
   * pertenece a un mes, sigue viva hasta que se cobra. */
  cobros(): Observable<Cobros> {
    return this.http.get<Cobros>(`${this.base}/cobros/`);
  }

  /** Usuarios de un gimnasio. Solo lo justo para saber a quién se le
   * restablece la contraseña: nombre, correo, rol y si está activo. */
  usuariosDe(uuid: string): Observable<UsuarioDeGimnasio[]> {
    return this.http.get<UsuarioDeGimnasio[]>(`${this.base}/tenants/${uuid}/usuarios/`);
  }

  /** Rescate de soporte: genera una contraseña nueva y la devuelve una sola
   * vez. Queda registrado en la auditoría del gimnasio. */
  restablecerPassword(uuid: string, usuarioId: number): Observable<PasswordRestablecida> {
    return this.http.post<PasswordRestablecida>(
      `${this.base}/tenants/${uuid}/restablecer-password/`,
      { usuario_id: usuarioId },
    );
  }

  /** Da de alta un gimnasio completo. La respuesta trae `acceso_inicial` con
   * la contraseña generada: es la única vez que se puede leer. */
  crearTenant(datos: TenantNuevo): Observable<TenantCreado> {
    return this.http.post<TenantCreado>(`${this.base}/tenants/`, datos);
  }

  actualizarTenant(uuid: string, datos: Partial<TenantConfiguracion>): Observable<TenantDetalle> {
    return this.http.patch<TenantDetalle>(`${this.base}/tenants/${uuid}/`, datos);
  }

  /** Cambia el ciclo de vida. `confirmacion` es el subdominio escrito a mano:
   * el backend lo exige porque suspender deja fuera a todo el gimnasio. */
  cambiarEstado(uuid: string, estado: EstadoTenant, confirmacion: string): Observable<TenantDetalle> {
    return this.http.post<TenantDetalle>(`${this.base}/tenants/${uuid}/estado/`, {
      estado,
      confirmacion,
    });
  }
}
