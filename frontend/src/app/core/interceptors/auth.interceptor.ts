import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';

/** Rutas públicas de autenticación: nunca llevan `Authorization` y un 401 ahí
 * significa "credenciales incorrectas", no "sesión caducada". Intentar
 * refrescar en esas rutas tapa el error real con "no hay refresh token
 * almacenado" (ya ocurrió una vez; no se debe repetir). */
const RUTAS_PUBLICAS = ['/login/', '/register/', '/refresh/'];

function esRutaPublica(url: string): boolean {
  return RUTAS_PUBLICAS.some((ruta) => url.includes(ruta));
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  const esPublica = esRutaPublica(req.url);
  const access = authService.obtenerAccessToken();

  const peticion = !esPublica && access
    ? req.clone({ setHeaders: { Authorization: `Bearer ${access}` } })
    : req;

  return next(peticion).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401 || esPublica) {
        return throwError(() => error);
      }

      return authService.refreshToken().pipe(
        switchMap((respuesta) => {
          const reintento = req.clone({
            setHeaders: { Authorization: `Bearer ${respuesta.access}` },
          });
          return next(reintento);
        }),
        catchError((errorRefresco: unknown) => {
          router.navigate(['/login']);
          return throwError(() => errorRefresco);
        }),
      );
    }),
  );
};
