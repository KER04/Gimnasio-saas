import { Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login').then((m) => m.Login),
  },
  {
    path: '',
    loadComponent: () =>
      import('./layout/layout-principal/layout-principal').then((m) => m.LayoutPrincipal),
    canActivate: [authGuard],
    children: [
      {
        path: 'dashboard',
        loadComponent: () =>
          import('./features/dashboard/dashboard').then((m) => m.Dashboard),
      },
      {
        path: 'clientes',
        loadComponent: () =>
          import('./features/clientes/listado/listado').then((m) => m.ClientesListado),
      },
      {
        // Antes de ':id': si no, 'nuevo' se interpretaría como un id.
        path: 'clientes/nuevo',
        loadComponent: () =>
          import('./features/clientes/formulario/formulario').then((m) => m.ClientesFormulario),
      },
      {
        path: 'clientes/:id/editar',
        loadComponent: () =>
          import('./features/clientes/formulario/formulario').then((m) => m.ClientesFormulario),
      },
      {
        path: 'clientes/:id',
        loadComponent: () =>
          import('./features/clientes/ficha/ficha').then((m) => m.ClientesFicha),
      },
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
    ],
  },
  { path: '**', redirectTo: 'login' },
];
