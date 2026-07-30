import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';

import { AuthService } from '../services/auth.service';

const RUTAS_SIN_TOKEN = ['/login/', '/register/', '/refresh/'];

function esRutaPublica(url: string): boolean {
  return RUTAS_SIN_TOKEN.some((ruta) => url.includes(ruta));
}

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);

  const accessToken = authService.getAccessToken();
  const requestConToken =
    accessToken && !esRutaPublica(req.url)
      ? req.clone({ setHeaders: { Authorization: `Bearer ${accessToken}` } })
      : req;

  return next(requestConToken).pipe(
    catchError((error: unknown) => {
      const esNoAutorizado = error instanceof HttpErrorResponse && error.status === 401;
      const esPeticionDeRefresh = req.url.includes('/refresh/');

      if (!esNoAutorizado || esPeticionDeRefresh) {
        return throwError(() => error);
      }

      return authService.refreshToken().pipe(
        switchMap((refreshResponse) => {
          const requestReintentada = req.clone({
            setHeaders: { Authorization: `Bearer ${refreshResponse.access}` },
          });
          return next(requestReintentada);
        }),
        catchError((refreshError: unknown) => {
          authService.clearSession();
          return throwError(() => refreshError);
        }),
      );
    }),
  );
};
