import { Component, OnInit, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';

/**
 * Shell de la aplicación autenticada (Parte A4). Cabecera con el nombre del
 * gimnasio, el usuario y su rol, y botón de cerrar sesión. Navegación
 * lateral en escritorio; en móvil se colapsa para no estorbar (RF-06:
 * pantalla táctil de mostrador, uso de ocho horas al día, sobrio).
 *
 * `GET /api/auth/me/` ahora expone `tenant.nombre_comercial` y `rol_nombre`
 * (ver `apps/autenticacion/views.py::MeView`), así que la cabecera muestra
 * el nombre real del gimnasio y del rol en vez del subdominio y "Rol #id".
 */
@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
})
export class Shell implements OnInit {
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly usuario = toSignal(this.authService.currentUser$, { initialValue: null });
  protected readonly menuMovilAbierto = signal(false);
  protected readonly nombreGimnasio = this.authService.nombreGimnasio;
  protected readonly nombreRol = this.authService.nombreRol;

  ngOnInit(): void {
    if (!this.usuario()) {
      this.authService.me().subscribe();
    }
  }

  alternarMenuMovil(): void {
    this.menuMovilAbierto.update((abierto) => !abierto);
  }

  cerrarMenuMovil(): void {
    this.menuMovilAbierto.set(false);
  }

  cerrarSesion(): void {
    this.authService.logout().subscribe({
      complete: () => this.router.navigateByUrl('/login'),
      error: () => this.router.navigateByUrl('/login'),
    });
  }
}
