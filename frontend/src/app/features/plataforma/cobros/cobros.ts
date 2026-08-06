import { Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { PlataformaService } from '../../../core/services/plataforma.service';
import {
  Cobros,
  DeudorPlataforma,
  ETIQUETAS_ESTADO_FACTURA,
  EstadoFactura,
} from '../../../core/models/plataforma.model';
import { precioParaMostrar } from '../../../core/utils/precio.util';

/**
 * Quién te debe dinero.
 *
 * Es, para ti, lo que el informe de cartera es para tus gimnasios. Se ordena
 * por DÍAS DE ATRASO y no por importe: quien lleva tres meses sin pagar es
 * una conversación más urgente que quien debe más pero va al día.
 */
@Component({
  selector: 'app-plataforma-cobros',
  templateUrl: './cobros.html',
})
export class PlataformaCobros {
  private readonly plataformaService = inject(PlataformaService);
  private readonly router = inject(Router);

  protected readonly datos = signal<Cobros | null>(null);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(null);
    this.plataformaService.cobros().subscribe({
      next: (datos) => {
        this.datos.set(datos);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar los cobros.');
      },
    });
  }

  protected irAlGimnasio(deudor: DeudorPlataforma): void {
    this.router.navigate(['/plataforma/gimnasios', deudor.tenant.uuid_publico]);
  }

  protected dinero(valor: string): string {
    return precioParaMostrar(valor);
  }

  protected etiquetaFactura(estado: EstadoFactura): string {
    return ETIQUETAS_ESTADO_FACTURA[estado];
  }

  protected fecha(valor: string | null): string {
    if (!valor) {
      return '—';
    }
    // Se le añade la hora para que el navegador no la interprete en UTC y la
    // retrase un día.
    const fecha = new Date(`${valor}T00:00:00`);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  /** El atraso en palabras. Cero no es "0 días": es que todavía está en plazo. */
  protected textoAtraso(dias: number): string {
    if (dias <= 0) {
      return 'Dentro del plazo';
    }
    return dias === 1 ? '1 día de atraso' : `${dias} días de atraso`;
  }

  protected claseAtraso(dias: number): string {
    if (dias <= 0) {
      return 'badge-neutral';
    }
    return dias > 30 ? 'badge-danger' : 'badge-warning';
  }
}
