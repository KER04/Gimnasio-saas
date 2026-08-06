import { Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';
import { plataformaGuard } from './core/guards/plataforma.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/auth/login/login').then((m) => m.Login),
  },
  // Panel del PROVEEDOR. Va antes que la ruta '' del gimnasio porque
  // comparten raíz y Angular resuelve por orden. Tiene su propio guard, su
  // propio login y su propio layout: no es una sección del gimnasio, es otra
  // aplicación que vive en el mismo dominio.
  {
    path: 'plataforma/login',
    loadComponent: () =>
      import('./features/plataforma/login/login-plataforma').then((m) => m.LoginPlataforma),
  },
  {
    path: 'plataforma',
    loadComponent: () =>
      import('./features/plataforma/layout/layout-plataforma').then((m) => m.LayoutPlataforma),
    canActivate: [plataformaGuard],
    children: [
      {
        path: 'gimnasios',
        loadComponent: () =>
          import('./features/plataforma/gimnasios/gimnasios').then((m) => m.PlataformaGimnasios),
      },
      {
        path: 'cuenta',
        loadComponent: () =>
          import('./features/plataforma/cuenta/cuenta-plataforma').then((m) => m.PlataformaCuenta),
      },
      {
        // Antes de ':uuid': si no, 'nuevo' se interpretaría como un uuid.
        path: 'gimnasios/nuevo',
        loadComponent: () =>
          import('./features/plataforma/gimnasios/nuevo-gimnasio').then(
            (m) => m.PlataformaNuevoGimnasio,
          ),
      },
      {
        path: 'gimnasios/:uuid',
        loadComponent: () =>
          import('./features/plataforma/gimnasios/ficha-gimnasio').then(
            (m) => m.PlataformaFichaGimnasio,
          ),
      },
      { path: '', pathMatch: 'full', redirectTo: 'gimnasios' },
    ],
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
      {
        path: 'reportes',
        loadComponent: () => import('./features/reportes/reportes').then((m) => m.Reportes),
      },
      {
        path: 'inventario',
        loadComponent: () =>
          import('./features/inventario/productos/productos').then((m) => m.InventarioProductos),
      },
      {
        path: 'pos',
        loadComponent: () => import('./features/pos/pos').then((m) => m.PuntoDeVenta),
      },
      {
        path: 'ventas',
        loadComponent: () =>
          import('./features/ventas/historial/historial').then((m) => m.VentasHistorial),
      },
      {
        path: 'asistencia',
        loadComponent: () =>
          import('./features/asistencia/check-in/check-in').then((m) => m.AsistenciaCheckIn),
      },
      {
        path: 'membresias',
        loadComponent: () =>
          import('./features/membresias/planes/planes').then((m) => m.PlanesListado),
      },
      {
        path: 'cuenta',
        loadComponent: () => import('./features/cuenta/cuenta').then((m) => m.MiCuenta),
      },
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
    ],
  },
  { path: '**', redirectTo: 'login' },
];
