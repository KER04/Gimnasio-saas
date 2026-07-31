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

      // En las rutas públicas de autenticación un 401 significa "credenciales
      // incorrectas", no "sesión caducada": no hay nada que refrescar.
      //
      // Intentarlo tenía una consecuencia peor que la petición de más: como
      // en ese momento no hay ningún refresh token guardado, el intento
      // fallaba con "No hay refresh token almacenado" y ESE error llegaba a
      // la pantalla, tapando el mensaje real del servidor. Un usuario que se
      // equivocaba de contraseña veía "Ocurrió un error inesperado" en lugar
      // de que su contraseña no era correcta.
      if (!esNoAutorizado || esRutaPublica(req.url)) {
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
