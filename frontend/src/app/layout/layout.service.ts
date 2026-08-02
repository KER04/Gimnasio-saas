import { Injectable, signal } from '@angular/core';

/**
 * Estado compartido del cajón lateral en móvil (RF-23). El header lo abre
 * con el botón de menú, el aside se cierra al navegar o con Escape, y
 * ambos leen el mismo signal en vez de encadenar `@Input/@Output`.
 */
@Injectable({ providedIn: 'root' })
export class LayoutService {
  private readonly abiertoSignal = signal(false);

  /** `true` mientras el cajón lateral está desplegado en móvil. */
  readonly abierto = this.abiertoSignal.asReadonly();

  abrir(): void {
    this.abiertoSignal.set(true);
  }

  cerrar(): void {
    this.abiertoSignal.set(false);
  }

  alternar(): void {
    this.abiertoSignal.update((valor) => !valor);
  }
}
