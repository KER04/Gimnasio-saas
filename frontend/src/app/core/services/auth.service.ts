import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, finalize, of, shareReplay, switchMap, tap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { TenantService } from '../tenant/tenant.service';
import { AuthResponse, LoginRequest, RefreshResponse, Sesion } from '../models/auth.model';

const CLAVE_ACCESS = 'gimnasio_access';
const CLAVE_REFRESH = 'gimnasio_refresh';

/**
 * Sesión del usuario autenticado: tokens, y el contexto que devuelve
 * `GET /api/auth/me/` (permisos, sede, rol, gimnasio).
 *
 * Los tokens viven en `localStorage` para sobrevivir recargas. La sesión
 * (permisos, usuario, etc.) vive en un signal y se repuebla al arrancar
 * llamando a `me()` si hay un access token guardado.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly tenantService = inject(TenantService);

  private readonly sesionSignal = signal<Sesion | null>(null);

  /** Sesión actual, o `null` si no hay usuario autenticado (todavía). */
  readonly sesion = this.sesionSignal.asReadonly();

  readonly estaAutenticado = computed<boolean>(() => this.sesionSignal() !== null);

  readonly permisos = computed<string[]>(() => this.sesionSignal()?.permisos ?? []);

  readonly sedeActual = computed(() => this.sesionSignal()?.sedes?.[0] ?? null);

  readonly nombreGimnasio = computed<string | null>(
    () => this.sesionSignal()?.tenant?.nombre_comercial ?? null,
  );

  readonly nombreRol = computed<string | null>(() => this.sesionSignal()?.rol_nombre ?? null);

  /**
   * Refresco en vuelo compartido entre peticiones concurrentes. El backend
   * ROTA el refresh token (revoca el anterior al usar uno nuevo): si dos
   * peticiones 401 en paralelo llaman cada una a `/refresh/`, la segunda
   * llega con un refresh ya revocado y la sesión se cierra sin motivo. Por
   * eso todas comparten esta única petición mientras está en vuelo.
   */
  private refrescoEnVuelo: Observable<RefreshResponse> | null = null;

  tienePermiso(codigo: string): boolean {
    return this.permisos().includes(codigo);
  }

  /** Autentica y, si sale bien, carga el contexto de sesión completo. */
  login(credenciales: LoginRequest): Observable<Sesion> {
    const cuerpo = this.tenantService.conSubdominio(credenciales);
    return this.http.post<AuthResponse>(`${environment.apiUrl}/auth/login/`, cuerpo).pipe(
      tap((respuesta) => this.guardarTokens(respuesta.access, respuesta.refresh)),
      // El login no trae permisos ni sedes: hay que pedirlos a `/me/`.
      switchMap(() => this.me()),
    );
  }

  /** Pide el contexto de sesión y lo deja guardado en el signal. */
  me(): Observable<Sesion> {
    return this.http.get<Sesion>(`${environment.apiUrl}/auth/me/`).pipe(
      tap((sesion) => this.sesionSignal.set(sesion)),
    );
  }

  /**
   * Cierra la sesión. Limpia tokens y estado local SIEMPRE, incluso si la
   * llamada al backend falla (token ya caducado, red caída, etc.): el
   * usuario debe poder salir aunque el servidor no responda.
   */
  logout(): Observable<void> {
    const refresh = this.obtenerRefreshToken();
    const limpiar = (): void => {
      this.limpiarSesionLocal();
      this.tenantService.olvidar();
    };

    if (!refresh) {
      limpiar();
      return of(void 0);
    }

    return this.http.post<void>(`${environment.apiUrl}/auth/logout/`, { refresh }).pipe(
      tap(() => limpiar()),
      catchError(() => {
        limpiar();
        return of(void 0);
      }),
    );
  }

  /** Rehidrata la sesión al arrancar la app, si hay un access token guardado. */
  rehidratar(): Observable<Sesion | null> {
    if (!this.obtenerAccessToken()) {
      return of(null);
    }
    return this.me().pipe(
      catchError(() => {
        this.limpiarSesionLocal();
        return of(null);
      }),
    );
  }

  refreshToken(): Observable<RefreshResponse> {
    if (this.refrescoEnVuelo) {
      return this.refrescoEnVuelo;
    }

    const refresh = this.obtenerRefreshToken();
    if (!refresh) {
      return throwError(() => new Error('No hay refresh token almacenado.'));
    }

    const peticion$ = this.http
      .post<RefreshResponse>(`${environment.apiUrl}/auth/refresh/`, { refresh })
      .pipe(
        tap((respuesta) => this.guardarTokens(respuesta.access, respuesta.refresh ?? refresh)),
        shareReplay({ bufferSize: 1, refCount: false }),
        finalize(() => {
          this.refrescoEnVuelo = null;
        }),
      );

    this.refrescoEnVuelo = peticion$;
    return peticion$;
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
      // Modo incógnito o almacenamiento lleno: la sesión sigue funcionando
      // en memoria durante esta pestaña, solo no sobrevive a un recargo.
    }
  }

  private limpiarSesionLocal(): void {
    this.sesionSignal.set(null);
    try {
      localStorage.removeItem(CLAVE_ACCESS);
      localStorage.removeItem(CLAVE_REFRESH);
    } catch {
      // Ver `guardarTokens`.
    }
  }
}
