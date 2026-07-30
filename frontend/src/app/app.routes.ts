import { Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';
import { permisoGuard } from './core/guards/permiso.guard';
import { Shell } from './layout/shell/shell';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login').then((m) => m.Login),
  },
  {
    path: '',
    component: Shell,
    canActivate: [authGuard],
    children: [
      {
        path: 'pos',
        canActivate: [permisoGuard('ventas.registrar')],
        loadComponent: () => import('./features/pos/pos').then((m) => m.Pos),
      },
      {
        path: 'sin-acceso',
        loadComponent: () =>
          import('./features/sin-acceso/sin-acceso').then((m) => m.SinAcceso),
      },
      { path: '', pathMatch: 'full', redirectTo: 'pos' },
    ],
  },
  { path: '**', redirectTo: '' },
];
