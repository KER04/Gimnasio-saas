import { Component, ElementRef, HostListener, computed, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { AuthService } from '../../core/services/auth.service';
import { LayoutService } from '../layout.service';

/**
 * Barra superior: marca del gimnasio, buscador global de clientes (RF-03,
 * disponible desde cualquier pantalla) y el chip de usuario con el menú de
 * cierre de sesión (RF-23: se abre con clic, nunca con hover).
 */
@Component({
  selector: 'app-header',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './header.html',
})
export class Header {
  protected readonly authService = inject(AuthService);
  protected readonly layoutService = inject(LayoutService);
  private readonly router = inject(Router);
  private readonly elementRef = inject(ElementRef<HTMLElement>);

  protected readonly busqueda = new FormControl('', { nonNullable: true });
  protected readonly menuAbierto = signal(false);

  protected readonly nombreCompleto = computed(() => this.authService.sesion()?.nombre ?? '');

  protected readonly iniciales = computed(() => {
    const partes = this.nombreCompleto().trim().split(/\s+/).filter(Boolean);
    if (partes.length === 0) {
      return '?';
    }
    if (partes.length === 1) {
      return partes[0].charAt(0).toUpperCase();
    }
    return (partes[0].charAt(0) + partes[partes.length - 1].charAt(0)).toUpperCase();
  });

  protected buscar(): void {
    const texto = this.busqueda.value.trim();
    this.busqueda.setValue('');
    this.menuAbierto.set(false);
    this.router.navigate(['/clientes'], texto ? { queryParams: { buscar: texto } } : {});
  }

  protected alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  protected cerrarSesion(): void {
    this.menuAbierto.set(false);
    this.authService.logout().subscribe(() => this.router.navigate(['/login']));
  }

  /** Cierra el menú de usuario al pulsar fuera de él. */
  @HostListener('document:click', ['$event'])
  protected alClicarFuera(evento: MouseEvent): void {
    if (this.menuAbierto() && !this.elementRef.nativeElement.contains(evento.target as Node)) {
      this.menuAbierto.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  protected alPulsarEscape(): void {
    this.menuAbierto.set(false);
  }
}
