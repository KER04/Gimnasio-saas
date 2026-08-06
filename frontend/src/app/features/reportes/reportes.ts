import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { forkJoin, of } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { ReportesService } from '../../core/services/reportes.service';
import {
  ReporteCaja,
  ReporteCartera,
  ReporteProductos,
  ReporteUtilidad,
  ReporteVentas,
} from '../../core/models/reporte.model';
import { precioParaMostrar } from '../../core/utils/precio.util';

/** Primer día del mes actual, en `YYYY-MM-DD`. */
function inicioDeMes(): string {
  const hoy = new Date();
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-01`;
}

function hoyISO(): string {
  const hoy = new Date();
  const mes = String(hoy.getMonth() + 1).padStart(2, '0');
  const dia = String(hoy.getDate()).padStart(2, '0');
  return `${hoy.getFullYear()}-${mes}-${dia}`;
}

/**
 * Informes (RF-08): caja, ventas y productos.
 *
 * La pantalla insiste en una distinción que es fácil de pasar por alto y
 * cara de confundir: **facturado** es lo que se vendió y **cobrado** es lo
 * que entró en caja. Con ventas a crédito nunca coinciden, y llamar "ventas"
 * a cualquiera de los dos sin decir cuál lleva a cuadrar mal.
 */
@Component({
  selector: 'app-reportes',
  imports: [ReactiveFormsModule],
  templateUrl: './reportes.html',
})
export class Reportes {
  private readonly reportesService = inject(ReportesService);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  protected readonly nombreSede = computed(() => this.authService.sedeActual()?.nombre ?? null);

  protected readonly desde = this.fb.nonNullable.control(inicioDeMes());
  protected readonly hasta = this.fb.nonNullable.control(hoyISO());
  protected readonly agrupar = signal<'dia' | 'mes'>('dia');

  protected readonly ventas = signal<ReporteVentas | null>(null);
  protected readonly caja = signal<ReporteCaja | null>(null);
  protected readonly productos = signal<ReporteProductos | null>(null);
  protected readonly cartera = signal<ReporteCartera | null>(null);
  protected readonly utilidad = signal<ReporteUtilidad | null>(null);

  /** Los márgenes solo los ve quien tenga `costos.ver`. Sin ese permiso ni
   * se pide el informe: el backend respondería 403. */
  protected readonly puedeVerCostos = computed(() => this.authService.tienePermiso('costos.ver'));

  protected readonly cargando = signal(true);
  /** Recarga de SOLO la tabla de caja (al cambiar día/mes), que no debe
   * vaciar el resto de la pantalla. */
  protected readonly cargandoCaja = signal(false);
  protected readonly error = signal<string | null>(null);

  /** `true` solo en la primerísima carga, cuando aún no hay nada que enseñar.
   * En las recargas posteriores se mantiene el contenido anterior a la vista:
   * si se sustituyera por un "Calculando…", la página se encogería de golpe y
   * el navegador perdería la posición del scroll, saltando al principio. */
  protected readonly cargandoPrimeraVez = computed(() => this.cargando() && this.ventas() === null);

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(null);
    const filtros = { desde: this.desde.value, hasta: this.hasta.value };

    // Las tres peticiones a la vez: son independientes y encadenarlas solo
    // haría esperar de más.
    forkJoin({
      ventas: this.reportesService.ventas(filtros),
      caja: this.reportesService.caja(filtros, this.agrupar()),
      productos: this.reportesService.productos(filtros),
      // La cartera NO recibe el rango: la deuda no pertenece a un periodo.
      cartera: this.reportesService.cartera(),
      utilidad: this.puedeVerCostos()
        ? this.reportesService.utilidad(filtros)
        : of(null),
    }).subscribe({
      next: ({ ventas, caja, productos, cartera, utilidad }) => {
        this.ventas.set(ventas);
        this.caja.set(caja);
        this.productos.set(productos);
        this.cartera.set(cartera);
        this.utilidad.set(utilidad);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar los informes.');
      },
    });
  }

  /**
   * Cambia entre día y mes recargando SOLO la tabla de caja.
   *
   * Antes llamaba a `cargar()`, que rehacía los cuatro informes y ponía la
   * pantalla en "Calculando…": el contenido desaparecía, la página se
   * encogía y el scroll saltaba arriba. Además pedía tres informes que no
   * habían cambiado.
   */
  protected cambiarAgrupacion(valor: 'dia' | 'mes'): void {
    if (this.agrupar() === valor || this.cargandoCaja()) {
      return;
    }
    this.agrupar.set(valor);
    this.cargandoCaja.set(true);
    this.reportesService
      .caja({ desde: this.desde.value, hasta: this.hasta.value }, valor)
      .subscribe({
        next: (caja) => {
          this.caja.set(caja);
          this.cargandoCaja.set(false);
        },
        error: () => {
          this.cargandoCaja.set(false);
          this.error.set('No se pudo cambiar la agrupación.');
        },
      });
  }

  /** Atajos de rango: lo que se consulta a diario en un mostrador. */
  protected rangoHoy(): void {
    this.desde.setValue(hoyISO());
    this.hasta.setValue(hoyISO());
    this.cargar();
  }

  protected rangoMes(): void {
    this.desde.setValue(inicioDeMes());
    this.hasta.setValue(hoyISO());
    this.cargar();
  }

  protected rangoTodo(): void {
    this.desde.setValue('');
    this.hasta.setValue('');
    this.cargar();
  }

  protected dinero(valor: string | undefined): string {
    return valor === undefined ? '—' : precioParaMostrar(valor);
  }

  /** Una utilidad negativa se pinta en rojo. Se comprueba sobre la CADENA
   * porque los importes llegan como texto y `Number` bastaría, pero el signo
   * es lo único que hace falta mirar. */
  protected esNegativo(valor: string): boolean {
    return valor.trim().startsWith('-');
  }

  /** `true` si el importe es cero. Se compara numéricamente y no por texto
   * porque el backend puede mandar `"0"`, `"0.00"` o `"0.0000"` según de qué
   * agregado venga. */
  protected esCero(valor: string): boolean {
    return Number(valor) === 0;
  }

  /** Cantidades sin decimales cuando son cero: "24" en vez de "24.00". */
  protected cantidad(valor: string): string {
    const numero = Number(valor);
    return Number.isInteger(numero) ? String(numero) : valor;
  }

  protected etiquetaPeriodo(periodo: string): string {
    const fecha = new Date(`${periodo}T00:00:00`);
    if (Number.isNaN(fecha.getTime())) {
      return periodo;
    }
    return this.agrupar() === 'mes'
      ? fecha.toLocaleDateString('es-CO', { month: 'long', year: 'numeric' })
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  /** `true` si queda dinero por cobrar en el rango. La diferencia puede ser
   * negativa (abonos de ventas anteriores), y eso no es una deuda. */
  protected readonly hayPorCobrar = computed(() => Number(this.ventas()?.diferencia ?? '0') > 0);

  /**
   * Salta a la ficha del cliente ABIERTA en la pestaña Deuda, que es donde
   * está el botón de registrar abono. Ver una deuda y tener que buscar dónde
   * se cobra son dos pasos que no tienen por qué existir.
   */
  protected irACobrar(clienteId: number | null): void {
    if (clienteId === null) {
      return;
    }
    this.router.navigate(['/clientes', clienteId], { queryParams: { tab: 'deuda' } });
  }
}
