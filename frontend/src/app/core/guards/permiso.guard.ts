import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { AuthService } from '../services/auth.service';
import { authGuard } from './auth.guard';

/**
 * Guard de permiso por código (p. ej. `'ventas.registrar'`).
 *
 * Ahora `GET /api/auth/me/` sí expone `permisos: string[]` (códigos del rol
 * del usuario, ver `apps/autenticacion/views.py::MeView`), así que este
 * guard puede comprobar de verdad el código en vez de limitarse a exigir
 * sesión iniciada (ver historial de este archivo para la limitación
 * anterior, ya resuelta).
 *
 * Carrera de arranque: tras un F5, `AuthService` rehidrata la sesión desde
 * `localStorage` de forma síncrona, pero puede no haber terminado aún de
 * refrescarla contra el backend. Si `authService.sesion()` ya tiene datos
 * (persistidos o de una navegación previa) se decide con eso al instante;
 * si NO hay nada todavía, se espera a que `me()` resuelva antes de decidir,
 * en vez de rechazar por una sesión que en realidad sí existe.
 *
 * IMPORTANTE: esto es usabilidad (no mostrar botones/rutas que el backend
 * va a rechazar), NO seguridad. La autorización real la impone el backend
 * con 403 en cada endpoint (`TienePermiso`); un usuario que manipule el
 * cliente no gana nada saltándose este guard.
 */
export function permisoGuard(permiso: string): CanActivateFn {
  return (route, state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    const resultadoSesion = authGuard(route, state);
    if (resultadoSesion !== true) {
      // Sin sesión: delega en authGuard (redirige a /login).
      return resultadoSesion;
    }

    const decidir = (permisos: string[]): true | UrlTree =>
      permisos.includes(permiso)
        ? true
        : router.createUrlTree(['/sin-acceso'], { queryParams: { permiso } });

    const sesionActual = authService.sesion();
    if (sesionActual) {
      return decidir(sesionActual.permisos);
    }

    return authService.me().pipe(
      map((sesion) => decidir(sesion.permisos)),
      catchError(() => of(router.createUrlTree(['/login'], { queryParams: { redirect: state.url } }))),
    );
  };
}
