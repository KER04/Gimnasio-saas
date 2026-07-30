import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { BehaviorSubject, Observable, finalize, of, shareReplay, tap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  AuthResponse,
  LoginRequest,
  RefreshResponse,
  RegisterRequest,
  Usuario,
} from '../models/auth.model';
import { subdominioDesdeHostname } from '../tenant/subdominio.util';

const ACCESS_TOKEN_KEY = 'gimnasio_access_token';
const REFRESH_TOKEN_KEY = 'gimnasio_refresh_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/auth`;

  private readonly currentUserSubject = new BehaviorSubject<Usuario | null>(null);
  readonly currentUser$ = this.currentUserSubject.asObservable();

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

  get isAuthenticated(): boolean {
    return !!this.getAccessToken();
  }

  login(credentials: LoginRequest): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.apiUrl}/login/`, this.conSubdominio(credentials))
      .pipe(tap((response) => this.handleAuthResponse(response)));
  }

  register(data: RegisterRequest): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${this.apiUrl}/register/`, this.conSubdominio(data))
      .pipe(tap((response) => this.handleAuthResponse(response)));
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

  me(): Observable<Usuario> {
    return this.http.get<Usuario>(`${this.apiUrl}/me/`).pipe(
      tap((usuario) => this.currentUserSubject.next(usuario)),
    );
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

  private clearSessionInternal(): void {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    this.currentUserSubject.next(null);
  }
}
