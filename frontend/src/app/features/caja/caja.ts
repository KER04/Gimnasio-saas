import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Observable, forkJoin } from 'rxjs';

import { AuthService } from '../../core/services/auth.service';
import { CajaService } from '../../core/services/caja.service';
import { SedesService } from '../../core/services/sedes.service';
import { SedeOrganizacion } from '../../core/models/sede.model';
import {
  CategoriaGasto,
  CategoriaIngreso,
  ETIQUETAS_FORMA_PAGO,
  FormaPago,
  Gasto,
  IngresoOtro,
} from '../../core/models/caja.model';
import { normalizarPrecio, precioParaMostrar, precioValido } from '../../core/utils/precio.util';

type ErroresDeCampo = Record<string, string | string[]>;
type Pestana = 'gastos' | 'ingresos';

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
 * Movimientos de caja que no son ventas: gastos (RF-24) e ingresos varios
 * (RF-07).
 *
 * Van juntos en una pantalla porque son las dos caras de lo mismo —dinero que
 * sale y dinero que entra sin venta detrás— y quien registra uno suele
 * registrar el otro en la misma sesión.
 */
@Component({
  selector: 'app-caja',
  imports: [ReactiveFormsModule],
  templateUrl: './caja.html',
})
export class CajaMovimientos {
  private readonly cajaService = inject(CajaService);
  private readonly sedesService = inject(SedesService);
  private readonly authService = inject(AuthService);
  private readonly fb = inject(FormBuilder);

  protected readonly etiquetasFormaPago = ETIQUETAS_FORMA_PAGO;
  protected readonly formasPago: FormaPago[] = ['efectivo', 'transferencia', 'tarjeta'];

  protected readonly pestana = signal<Pestana>('gastos');

  protected readonly gastos = signal<Gasto[]>([]);
  protected readonly ingresos = signal<IngresoOtro[]>([]);
  protected readonly categoriasGasto = signal<CategoriaGasto[]>([]);
  protected readonly categoriasIngreso = signal<CategoriaIngreso[]>([]);
  protected readonly sedes = signal<SedeOrganizacion[]>([]);

  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  protected readonly desde = this.fb.nonNullable.control(inicioDeMes());
  protected readonly hasta = this.fb.nonNullable.control(hoyISO());

  protected readonly panelAbierto = signal(false);
  protected readonly editandoId = signal<number | null>(null);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});
  protected readonly ocupadoId = signal<number | null>(null);

  protected readonly formulario = this.fb.nonNullable.group({
    categoria: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    sede: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    // Texto, no `number`: el dinero se trata como cadena en todo el proyecto
    // y un input numérico cambia el valor con la rueda del ratón.
    monto: ['', [Validators.required, precioValido]],
    fecha: [hoyISO(), [Validators.required]],
    descripcion: ['', [Validators.required]],
    forma_pago: this.fb.nonNullable.control<FormaPago>('efectivo'),
  });

  /** Totales del periodo, para no tener que sumar a mano. */
  protected readonly totalGastos = computed(() =>
    this.gastos().reduce((suma, g) => suma + Number(g.monto), 0),
  );
  protected readonly totalIngresos = computed(() =>
    this.ingresos().reduce((suma, i) => suma + Number(i.monto), 0),
  );

  constructor() {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(null);
    const filtros = { desde: this.desde.value, hasta: this.hasta.value };

    forkJoin({
      gastos: this.cajaService.listarGastos(filtros),
      ingresos: this.cajaService.listarIngresos(filtros),
      categoriasGasto: this.cajaService.listarCategoriasGasto(),
      categoriasIngreso: this.cajaService.listarCategoriasIngreso(),
      sedes: this.sedesService.listar(),
    }).subscribe({
      next: ({ gastos, ingresos, categoriasGasto, categoriasIngreso, sedes }) => {
        this.gastos.set(gastos);
        this.ingresos.set(ingresos);
        this.categoriasGasto.set(categoriasGasto);
        this.categoriasIngreso.set(categoriasIngreso);
        this.sedes.set(sedes.filter((s) => s.activa));
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set('No se pudieron cargar los movimientos.');
      },
    });
  }

  protected cambiarPestana(valor: Pestana): void {
    if (this.pestana() === valor) {
      return;
    }
    this.pestana.set(valor);
    this.cerrarPanel();
  }

  protected rangoMes(): void {
    this.desde.setValue(inicioDeMes());
    this.hasta.setValue(hoyISO());
    this.cargar();
  }

  // --- Alta y edición --------------------------------------------------

  protected abrirAlta(): void {
    this.editandoId.set(null);
    this.erroresCampo.set({});
    // Con una sola sede se preselecciona: preguntarlo sería pedir algo que ya
    // se sabe.
    const sedes = this.sedes();
    this.formulario.reset({
      categoria: '',
      sede: sedes.length === 1 ? sedes[0].id : '',
      monto: '',
      fecha: hoyISO(),
      descripcion: '',
      forma_pago: 'efectivo',
    });
    this.panelAbierto.set(true);
  }

  protected abrirEdicionGasto(gasto: Gasto): void {
    this.editandoId.set(gasto.id);
    this.erroresCampo.set({});
    this.formulario.reset({
      categoria: gasto.categoria_gasto,
      sede: gasto.sede,
      monto: precioParaMostrar(gasto.monto),
      fecha: gasto.fecha,
      descripcion: gasto.descripcion,
      forma_pago: 'efectivo',
    });
    this.panelAbierto.set(true);
  }

  protected abrirEdicionIngreso(ingreso: IngresoOtro): void {
    this.editandoId.set(ingreso.id);
    this.erroresCampo.set({});
    this.formulario.reset({
      categoria: ingreso.categoria_ingreso,
      sede: ingreso.sede,
      monto: precioParaMostrar(ingreso.monto),
      fecha: ingreso.fecha,
      descripcion: ingreso.descripcion,
      forma_pago: ingreso.forma_pago,
    });
    this.panelAbierto.set(true);
  }

  protected cerrarPanel(): void {
    this.panelAbierto.set(false);
    this.editandoId.set(null);
    this.erroresCampo.set({});
  }

  protected guardar(): void {
    if (this.guardando()) {
      return;
    }
    this.formulario.markAllAsTouched();
    if (this.formulario.invalid) {
      return;
    }

    this.guardando.set(true);
    this.erroresCampo.set({});

    const v = this.formulario.getRawValue();
    const monto = normalizarPrecio(v.monto) ?? '0';
    const id = this.editandoId();
    const esGasto = this.pestana() === 'gastos';

    // Tipado explícito: sin él, el ternario produce una unión de
    // `Observable<Gasto> | Observable<IngresoOtro>` y TypeScript no puede
    // llamar a `subscribe` sobre una unión de firmas.
    const peticion$: Observable<Gasto | IngresoOtro> = esGasto
      ? id === null
        ? this.cajaService.crearGasto({
            categoria_gasto: v.categoria as number,
            sede: v.sede as number,
            monto,
            fecha: v.fecha,
            descripcion: v.descripcion.trim(),
          })
        : this.cajaService.actualizarGasto(id, {
            categoria_gasto: v.categoria as number,
            sede: v.sede as number,
            monto,
            fecha: v.fecha,
            descripcion: v.descripcion.trim(),
          })
      : id === null
        ? this.cajaService.crearIngreso({
            categoria_ingreso: v.categoria as number,
            sede: v.sede as number,
            monto,
            forma_pago: v.forma_pago,
            fecha: v.fecha,
            descripcion: v.descripcion.trim(),
          })
        : this.cajaService.actualizarIngreso(id, {
            categoria_ingreso: v.categoria as number,
            sede: v.sede as number,
            monto,
            forma_pago: v.forma_pago,
            fecha: v.fecha,
            descripcion: v.descripcion.trim(),
          });

    peticion$.subscribe({
      next: () => {
        this.guardando.set(false);
        this.cerrarPanel();
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        if (error instanceof HttpErrorResponse && error.error && typeof error.error === 'object') {
          this.erroresCampo.set(error.error as ErroresDeCampo);
        } else {
          this.error.set('No se pudo guardar.');
        }
      },
    });
  }

  // --- Borrado ---------------------------------------------------------

  protected eliminarGasto(gasto: Gasto): void {
    if (!confirm(`¿Eliminar el gasto "${gasto.descripcion}" de ${this.dinero(gasto.monto)}? Queda registrado en la auditoría con lo que había, pero la fila desaparece.`)) {
      return;
    }
    this.borrar(gasto.id, this.cajaService.eliminarGasto(gasto.id));
  }

  protected eliminarIngreso(ingreso: IngresoOtro): void {
    if (!confirm(`¿Eliminar el ingreso "${ingreso.descripcion}" de ${this.dinero(ingreso.monto)}? Queda registrado en la auditoría, pero dejará de sumar en el corte de caja.`)) {
      return;
    }
    this.borrar(ingreso.id, this.cajaService.eliminarIngreso(ingreso.id));
  }

  private borrar(id: number, peticion$: Observable<void>): void {
    this.ocupadoId.set(id);
    this.error.set(null);
    peticion$.subscribe({
      next: () => {
        this.ocupadoId.set(null);
        this.cargar();
      },
      error: () => {
        this.ocupadoId.set(null);
        this.error.set('No se pudo eliminar.');
      },
    });
  }

  // --- Presentación ----------------------------------------------------

  protected erroresDe(campo: string): string[] {
    const valor = this.erroresCampo()[campo];
    if (valor === undefined) {
      return [];
    }
    return Array.isArray(valor) ? valor : [valor];
  }

  /** Los errores de categoría llegan con el nombre del campo del backend,
   * que difiere entre gastos e ingresos. */
  protected erroresDeCategoria(): string[] {
    return [
      ...this.erroresDe('categoria_gasto'),
      ...this.erroresDe('categoria_ingreso'),
    ];
  }

  protected dinero(valor: string | number): string {
    return precioParaMostrar(String(valor));
  }

  protected fecha(valor: string): string {
    // Se le añade la hora para que el navegador no la interprete en UTC y la
    // retrase un día.
    const fecha = new Date(`${valor}T00:00:00`);
    return Number.isNaN(fecha.getTime())
      ? valor
      : fecha.toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  protected nombreCategoriaIngreso(c: CategoriaIngreso): string {
    return c.subcategoria ? `${c.nombre} · ${c.subcategoria}` : c.nombre;
  }
}
