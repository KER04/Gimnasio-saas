import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { BehaviorSubject, Observable, finalize, of, shareReplay, tap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AuthResponse,
  LoginRequest,
  RefreshResponse,
  RegisterRequest,
  Sede,
  Sesion,
  Usuario,
} from '../models/auth.model';
import { subdominioDesdeHostname } from '../tenant/subdominio.util';

const ACCESS_TOKEN_KEY = 'gimnasio_access_token';
const REFRESH_TOKEN_KEY = 'gimnasio_refresh_token';
const SESION_KEY = 'gimnasio_sesion';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/auth`;

  private readonly currentUserSubject = new BehaviorSubject<Usuario | null>(null);
  readonly currentUser$ = this.currentUserSubject.asObservable();

  /**
   * Contexto completo de la sesión (`GET /api/auth/me/`): usuario, tenant,
   * sedes asignadas y permisos del rol. Se persiste en `localStorage` para
   * que un F5 no deje momentáneamente a la aplicación sin sede ni permisos
   * mientras `me()` responde (se rehidrata de forma síncrona en el
   * constructor y luego se refresca en segundo plano contra el backend).
   */
  private readonly sesionSignal = signal<Sesion | null>(this.leerSesionPersistida());
  readonly sesion = this.sesionSignal.asReadonly();

  /** Códigos de permiso del rol actual (usabilidad, no seguridad: ver `tienePermiso`). */
  readonly permisos = computed<string[]>(() => this.sesionSignal()?.permisos ?? []);

  /** Primera sede asignada al usuario, o `null` si no tiene ninguna.
   * TODO: cuando exista selector de sede, dejar de asumir "la primera". */
  readonly sedeActual = computed<Sede | null>(() => this.sesionSignal()?.sedes[0] ?? null);

  readonly nombreGimnasio = computed<string | null>(
    () => this.sesionSignal()?.tenant.nombre_comercial ?? null,
  );

  readonly nombreRol = computed<string | null>(() => this.sesionSignal()?.rol_nombre ?? null);

  /**
   * Petición de refresh actualmente en vuelo, si la hay.
   *
   * El backend usa ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION: cada
   * refresh invalida el token anterior. Si varias peticiones caducan a la vez
   * y cada una lanzara su propio refresh, solo la primera tendría éxito y las
   * demás recibirían un 401 por usar un token ya revocado, cerrando la sesión
   * del usuario. Compartimos una única petición entre todos los interesados.
   */
  private refreshEnCurso$: Observable<RefreshResponse> | null = null;

  constructor() {
    const sesionPersistida = this.sesionSignal();
    if (sesionPersistida) {
      this.currentUserSubject.next(sesionPersistida);
    }
    // Rehidratación en segundo plano: si hay sesión (token presente), refresca
    // contra el backend por si algo cambió (rol, permisos, sedes) desde la
    // última visita.
    if (this.isAuthenticated) {
      this.me().subscribe({ error: () => void 0 });
    }
  }

  get isAuthenticated(): boolean {
    return !!this.getAccessToken();
  }

  login(credentials: LoginRequest): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.apiUrl}/login/`, this.conSubdominio(credentials))
      .pipe(
        tap((response) => this.handleAuthResponse(response)),
        tap(() => this.me().subscribe({ error: () => void 0 })),
      );
  }

  register(data: RegisterRequest): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.apiUrl}/register/`, this.conSubdominio(data))
      .pipe(
        tap((response) => this.handleAuthResponse(response)),
        tap(() => this.me().subscribe({ error: () => void 0 })),
      );
  }

  refreshToken(): Observable<RefreshResponse> {
    if (this.refreshEnCurso$) {
      return this.refreshEnCurso$;
    }

    const refresh = this.getRefreshToken();
    if (!refresh) {
      return throwError(() => new Error('No hay refresh token almacenado.'));
    }

    this.refreshEnCurso$ = this.http
      .post<RefreshResponse>(`${this.apiUrl}/refresh/`, { refresh })
      .pipe(
        tap((response) => {
          this.setAccessToken(response.access);
          if (response.refresh) {
            this.setRefreshToken(response.refresh);
          }
        }),
        finalize(() => {
          this.refreshEnCurso$ = null;
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );

    return this.refreshEnCurso$;
  }

  logout(): Observable<void> {
    const refresh = this.getRefreshToken();
    if (!refresh) {
      this.clearSessionInternal();
      return of(void 0);
    }

    return this.http.post<void>(`${this.apiUrl}/logout/`, { refresh }).pipe(
      finalize(() => this.clearSessionInternal()),
    );
  }

  /** `GET /api/auth/me/`: contexto completo de la sesión (usuario, tenant,
   * sedes y permisos). Puebla `sesion` (signal) y la persiste. */
  me(): Observable<Sesion> {
    return this.http.get<Sesion>(`${this.apiUrl}/me/`).pipe(
      tap((sesion) => {
        this.currentUserSubject.next(sesion);
        this.sesionSignal.set(sesion);
        this.guardarSesionPersistida(sesion);
      }),
    );
  }

  /** Comprueba si la sesión actual tiene el código de permiso indicado.
   * SOLO usabilidad (ocultar/mostrar UI): la autorización real la impone
   * el backend con 403. Ver `permisoGuard`. */
  tienePermiso(codigo: string): boolean {
    return this.permisos().includes(codigo);
  }

  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_TOKEN_KEY);
  }

  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  }

  /** Limpia la sesión local (tokens y usuario actual). Usado también por el
   * interceptor cuando el refresh token falla. */
  clearSession(): void {
    this.clearSessionInternal();
  }

  /**
   * Si `payload` NO trae ya su propio `subdominio`, lo rellena con el que
   * se deduce del hostname actual del navegador (útil cuando Angular y el
   * API no comparten host, p. ej. `gimx.tuapp.com` sirviendo la app pero
   * pegando a `api.tuapp.com`: el backend nunca vería el subdominio del
   * gimnasio en el `Host` de la petición sin esto).
   *
   * Si no se puede deducir ninguno (p. ej. `localhost` a secas, o el
   * propio dominio "desnudo" sin subdominio), NO se añade el campo: el
   * backend cae entonces a su propio respaldo (subdominio del Host de la
   * petición) o responde 400 con un mensaje claro si tampoco tiene con qué
   * resolver el tenant.
   */
  private conSubdominio<T extends { subdominio?: string }>(payload: T): T {
    if (payload.subdominio) {
      return payload;
    }

    const subdominio = subdominioDesdeHostname(window.location.hostname);
    return subdominio ? { ...payload, subdominio } : payload;
  }

  private handleAuthResponse(response: AuthResponse): void {
    this.setAccessToken(response.access);
    this.setRefreshToken(response.refresh);
    this.currentUserSubject.next(response.user);
  }

  private setAccessToken(token: string): void {
    localStorage.setItem(ACCESS_TOKEN_KEY, token);
  }

  private setRefreshToken(token: string): void {
    localStorage.setItem(REFRESH_TOKEN_KEY, token);
  }

  private guardarSesionPersistida(sesion: Sesion): void {
    try {
      localStorage.setItem(SESION_KEY, JSON.stringify(sesion));
    } catch {
      // localStorage lleno o inaccesible (modo privado, etc.): la sesión
      // sigue funcionando en memoria para esta pestaña, solo se pierde la
      // rehidratación instantánea en el próximo F5.
    }
  }

  private leerSesionPersistida(): Sesion | null {
    try {
      const bruto = localStorage.getItem(SESION_KEY);
      return bruto ? (JSON.parse(bruto) as Sesion) : null;
    } catch {
      return null;
    }
  }

  private clearSessionInternal(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(SESION_KEY);
    this.currentUserSubject.next(null);
    this.sesionSignal.set(null);
  }
}
