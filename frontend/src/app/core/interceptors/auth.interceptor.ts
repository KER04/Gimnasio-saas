import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, switchMap, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';
import { PREFIJO_API_PLATAFORMA, PlataformaService } from '../services/plataforma.service';

/** Rutas públicas de autenticación: nunca llevan `Authorization` y un 401 ahí
 * significa "credenciales incorrectas", no "sesión caducada". Intentar
 * refrescar en esas rutas tapa el error real con "no hay refresh token
 * almacenado" (ya ocurrió una vez; no se debe repetir). */
const RUTAS_PUBLICAS = ['/login/', '/register/', '/refresh/'];

function esRutaPublica(url: string): boolean {
  return RUTAS_PUBLICAS.some((ruta) => url.includes(ruta));
}

/**
 * `true` si la petición va al panel del proveedor.
 *
 * La aplicación maneja DOS sesiones independientes con dos tokens distintos,
 * y mandar el que no toca no es un fallo cosmético: el backend rechaza de
 * plano el token de gimnasio en `/api/plataforma/` y viceversa (los ámbitos
 * están separados a propósito), así que confundirlos deja la pantalla
 * dando 401 sin motivo aparente.
 */
function esPeticionDePlataforma(url: string): boolean {
  return url.includes(PREFIJO_API_PLATAFORMA);
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const plataformaService = inject(PlataformaService);
  const router = inject(Router);

  const esPublica = esRutaPublica(req.url);
  const esPlataforma = esPeticionDePlataforma(req.url);

  const access = esPlataforma
    ? plataformaService.obtenerAccessToken()
    : authService.obtenerAccessToken();

  const conToken = (peticion: HttpRequest<unknown>, token: string) =>
    peticion.clone({ setHeaders: { Authorization: `Bearer ${token}` } });

  const peticion = !esPublica && access ? conToken(req, access) : req;

  return next(peticion).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401 || esPublica) {
        return throwError(() => error);
      }

      // Cada sesión se refresca contra SU endpoint y, si no se puede, cae a
      // SU pantalla de acceso: expulsar al operario del gimnasio porque
      // caducó la sesión del panel (o al revés) sería absurdo.
      const refresco: Observable<{ access: string }> = esPlataforma
        ? plataformaService.refrescar()
        : authService.refreshToken();

      return refresco.pipe(
        switchMap((respuesta) => next(conToken(req, respuesta.access))),
        catchError((errorRefresco: unknown) => {
          router.navigate([esPlataforma ? '/plataforma/login' : '/login']);
          return throwError(() => errorRefresco);
        }),
      );
    }),
  );
};
