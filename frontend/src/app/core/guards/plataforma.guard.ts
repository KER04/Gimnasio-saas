import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { PlataformaService } from '../services/plataforma.service';

/**
 * Protege el panel del proveedor. Es una sesión APARTE de la del gimnasio:
 * estar dentro de un gimnasio no da acceso aquí, y tener sesión aquí no
 * abre ningún gimnasio.
 */
export const plataformaGuard: CanActivateFn = (_route, state) => {
  const plataformaService = inject(PlataformaService);
  const router = inject(Router);

  if (plataformaService.estaAutenticado()) {
    return true;
  }

  return router.createUrlTree(['/plataforma/login'], {
    queryParams: { redirigirA: state.url },
  });
};
