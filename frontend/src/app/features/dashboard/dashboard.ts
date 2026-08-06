import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { AsistenciasService } from '../../core/services/asistencias.service';
import { AuthService } from '../../core/services/auth.service';
import { MembresiasService } from '../../core/services/membresias.service';
import { ProductosService } from '../../core/services/productos.service';
import { ReportesService } from '../../core/services/reportes.service';
import { Asistencia } from '../../core/models/asistencia.model';
import { MembresiaPorVencer } from '../../core/models/membresia.model';
import { Producto } from '../../core/models/producto.model';
import { ReporteCaja, ReporteCartera } from '../../core/models/reporte.model';
import { precioParaMostrar } from '../../core/utils/precio.util';

function hoyISO(): string {
  const hoy = new Date();
  const mes = String(hoy.getMonth() + 1).padStart(2, '0');
  const dia = String(hoy.getDate()).padStart(2, '0');
  return `${hoy.getFullYear()}-${mes}-${dia}`;
}

/**
 * Panel de inicio: el estado del gimnasio hoy y lo que reclama atención.
 *
 * No añade ningún endpoint: reúne los que ya existen (caja, cartera,
 * vencimientos, inventario y asistencia) y enlaza a la pantalla donde se
 * ACTÚA sobre cada cosa. Un panel que solo informa obliga a buscar dónde se
 * resuelve lo que acaba de enseñarte; este lleva.
 *
 * Cada bloque depende de un permiso distinto, así que cada petición se pide
 * solo si corresponde y, si falla, se degrada sola: un informe caído deja su
 * tarjeta vacía en vez de tumbar la pantalla de entrada de la aplicación.
 */
@Component({
  selector: 'app-dashboard',
  imports: [RouterLink],
  templateUrl: './dashboard.html',
})
export class Dashboard {
  private readonly reportesService = inject(ReportesService);
  private readonly membresiasService = inject(MembresiasService);
  private readonly productosService = inject(ProductosService);
  private readonly asistenciasService = inject(AsistenciasService);
  private readonly authService = inject(AuthService);

  protected readonly nombreGimnasio = computed(() => this.authService.nombreGimnasio() ?? '');
  protected readonly nombreUsuario = computed(() => this.authService.sesion()?.nombre ?? '');
  private readonly sedeId = computed(() => this.authService.sedeActual()?.id ?? null);

  protected readonly puedeVerReportes = computed(() => this.authService.tienePermiso('reportes.ver'));
  protected readonly puedeVerInventario = computed(() => this.authService.tienePermiso('inventario.ver'));

  protected readonly caja = signal<ReporteCaja | null>(null);
  protected readonly cartera = signal<ReporteCartera | null>(null);
  protected readonly porVencer = signal<MembresiaPorVencer[]>([]);
  protected readonly bajoMinimo = signal<Producto[]>([]);
  protected readonly ingresosHoy = signal<Asistencia[]>([]);
  protected readonly cargando = signal(true);

  /** Caja de hoy. Si no hubo movimiento no hay fila y el total es cero. */
  protected readonly cajaHoy = computed(() => this.caja()?.totales.total_recibido ?? '0');

  /** Las ya vencidas y las que vencen hoy: las que exigen llamar HOY. */
  protected readonly vencimientosUrgentes = computed(
    () => this.porVencer().filter((m) => m.dias_restantes <= 0).length,
  );

  constructor() {
    const hoy = hoyISO();
    const sede = this.sedeId();

    // `catchError` por petición y no uno global: si un informe falla, su
    // tarjeta queda vacía pero las demás siguen mostrándose.
    forkJoin({
      caja: this.puedeVerReportes()
        ? this.reportesService.caja({ desde: hoy, hasta: hoy }).pipe(catchError(() => of(null)))
        : of(null),
      cartera: this.puedeVerReportes()
        ? this.reportesService.cartera().pipe(catchError(() => of(null)))
        : of(null),
      porVencer: this.puedeVerReportes()
        ? this.membresiasService.porVencer().pipe(catchError(() => of<MembresiaPorVencer[]>([])))
        : of<MembresiaPorVencer[]>([]),
      productos:
        this.puedeVerInventario() && sede !== null
          ? this.productosService.listar(sede).pipe(catchError(() => of<Producto[]>([])))
          : of<Producto[]>([]),
      asistencias: this.puedeVerReportes()
        ? this.asistenciasService.listar({ desde: hoy }).pipe(catchError(() => of(null)))
        : of(null),
    }).subscribe(({ caja, cartera, porVencer, productos, asistencias }) => {
      this.caja.set(caja);
      this.cartera.set(cartera);
      this.porVencer.set(porVencer);
      this.bajoMinimo.set(productos.filter((p) => this.estaBajoMinimo(p)));
      this.ingresosHoy.set(asistencias?.results ?? []);
      this.cargando.set(false);
    });
  }

  /** Mismo criterio que la pantalla de inventario: solo avisa si hay un
   * mínimo configurado, porque con mínimo cero todo estaría "bajo mínimo". */
  private estaBajoMinimo(producto: Producto): boolean {
    const minimo = producto.stock_minimo === null ? 0 : Number(producto.stock_minimo);
    const stock = producto.stock === null ? 0 : Number(producto.stock);
    return minimo > 0 && stock <= minimo;
  }

  protected dinero(valor: string): string {
    return precioParaMostrar(valor);
  }

  protected cantidad(valor: string | null): string {
    const numero = Number(valor ?? '0');
    return Number.isInteger(numero) ? String(numero) : String(valor);
  }

  protected textoVencimiento(dias: number): string {
    if (dias < 0) {
      const vencidos = Math.abs(dias);
      return vencidos === 1 ? 'venció ayer' : `venció hace ${vencidos} días`;
    }
    if (dias === 0) {
      return 'vence hoy';
    }
    return dias === 1 ? 'vence mañana' : `vence en ${dias} días`;
  }

  protected claseVencimiento(dias: number): string {
    return dias <= 0 ? 'badge-danger' : 'badge-warning';
  }

  protected hora(iso: string): string {
    const f = new Date(iso);
    return Number.isNaN(f.getTime())
      ? iso
      : f.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit', hour12: false });
  }

  /** Saludo según la hora: un panel que se abre decenas de veces al día
   * agradece no ser idéntico siempre. */
  protected readonly saludo = computed(() => {
    const hora = new Date().getHours();
    if (hora < 12) {
      return 'Buenos días';
    }
    return hora < 19 ? 'Buenas tardes' : 'Buenas noches';
  });
}
