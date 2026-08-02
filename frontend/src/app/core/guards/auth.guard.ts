import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from '../services/auth.service';

/** Protege las rutas que requieren sesión. Sin sesión, redirige a `/login`
 * guardando la URL de destino en `redirigirA` para volver ahí tras entrar. */
export const authGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.estaAutenticado()) {
    return true;
  }

  return router.createUrlTree(['/login'], {
    queryParams: { redirigirA: state.url },
  });
};
