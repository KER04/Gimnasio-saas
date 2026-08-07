import { Component, input, model } from '@angular/core';

/**
 * Qué filas mostrar según su estado de alta.
 *
 * `'activos'` es siempre el valor por defecto: al abrir una pantalla se
 * quiere ver con qué se está trabajando, no el histórico completo.
 */
export type FiltroEstado = 'activos' | 'inactivos' | 'todos';

/**
 * Filtro de tres posiciones: activos, inactivos o todos.
 *
 * Sustituye a la casilla "ver también los dados de baja", que solo tenía dos
 * estados y no permitía la pregunta que más se hace al buscar algo perdido:
 * "enséñame SOLO lo dado de baja". Con la casilla había que mirarlo todo
 * mezclado y buscar a ojo.
 *
 * Las etiquetas son configurables porque el mismo control sirve para cosas
 * que no se llaman igual: un usuario está "sin acceso", una sede está
 * "cerrada" y un proceso de medidas está "cerrado".
 */
@Component({
  selector: 'app-filtro-estado',
  template: `
    <div class="inline-flex rounded-lg border border-outline-variant p-0.5" role="group"
         [attr.aria-label]="etiquetaGrupo()">
      @for (opcion of opciones(); track opcion.valor) {
        <button
          type="button"
          class="rounded-[6px] px-3 py-1.5 text-sm font-medium transition-colors"
          [class]="valor() === opcion.valor
            ? 'bg-primary text-on-primary'
            : 'text-on-surface-variant hover:bg-surface-container-low'"
          [attr.aria-pressed]="valor() === opcion.valor"
          (click)="valor.set(opcion.valor)"
        >
          {{ opcion.etiqueta }}
        </button>
      }
    </div>
  `,
})
export class FiltroEstadoControl {
  /** Enlace bidireccional: la pantalla reacciona al cambio con un `effect`
   * o recargando en el manejador, según le convenga. */
  readonly valor = model<FiltroEstado>('activos');

  readonly etiquetaActivos = input('Activos');
  readonly etiquetaInactivos = input('Inactivos');
  readonly etiquetaGrupo = input('Filtrar por estado');

  protected opciones(): { valor: FiltroEstado; etiqueta: string }[] {
    return [
      { valor: 'activos', etiqueta: this.etiquetaActivos() },
      { valor: 'inactivos', etiqueta: this.etiquetaInactivos() },
      { valor: 'todos', etiqueta: 'Todos' },
    ];
  }
}
