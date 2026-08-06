import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { catchError, concatMap, debounceTime, distinctUntilChanged, from, of, toArray } from 'rxjs';

import { AuthService } from '../../../core/services/auth.service';
import { ProductosService } from '../../../core/services/productos.service';
import {
  CategoriaProducto,
  ETIQUETAS_TIPO_MOVIMIENTO,
  MovimientoInventario,
  Producto,
  TipoMovimiento,
} from '../../../core/models/producto.model';
import { formatearMonto, normalizarPrecio, precioParaMostrar, precioValido } from '../../../core/utils/precio.util';

/** Errores de campo tal como los devuelve DRF: `{"campo": "texto" | [...]}`. */
type ErroresDeCampo = Record<string, string | string[]>;

/** Una línea de la compra en lote: qué producto entra y a qué costo. */
interface LineaCompra {
  producto: Producto;
  cantidad: number;
  costoUnitario: string;
}

/**
 * Inventario: catálogo de productos, categorías y movimientos de existencias.
 *
 * Las existencias NO se editan como un campo más: se mueven registrando una
 * entrada o un ajuste en el kardex, y es un disparador de PostgreSQL quien
 * actualiza el stock y calcula el saldo. Por eso el formulario de producto no
 * tiene casilla de stock: permitirlo desincronizaría el libro de movimientos,
 * que es justo lo que el diseño de la base impide.
 */
@Component({
  selector: 'app-inventario-productos',
  imports: [ReactiveFormsModule],
  templateUrl: './productos.html',
})
export class InventarioProductos {
  private readonly productosService = inject(ProductosService);
  private readonly authService = inject(AuthService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly puedeGestionar = computed(() => this.authService.tienePermiso('inventario.gestionar'));
  protected readonly puedeVerCostos = computed(() => this.authService.tienePermiso('costos.ver'));

  protected readonly sedeId = computed(() => this.authService.sedeActual()?.id ?? null);
  protected readonly nombreSede = computed(() => this.authService.sedeActual()?.nombre ?? null);

  protected readonly etiquetasTipo = ETIQUETAS_TIPO_MOVIMIENTO;

  // --- Catálogo ---
  protected readonly buscar = this.fb.nonNullable.control('');
  protected readonly productos = signal<Producto[]>([]);
  /** TODAS las categorías, dadas de baja incluidas. Se cargan enteras porque
   * el panel de categorías es el único sitio desde el que se puede volver a
   * activar una: si solo pidiera las activas, dar de baja sería un viaje sin
   * retorno y habría que reactivarla por SQL. Para ELEGIR categoría al crear
   * un producto se usa `categoriasParaElegir`, que sí filtra. */
  protected readonly categorias = signal<CategoriaProducto[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);

  // --- Panel de producto ---
  protected readonly panelProducto = signal(false);
  protected readonly productoEditando = signal<Producto | null>(null);
  protected readonly guardando = signal(false);
  protected readonly erroresCampo = signal<ErroresDeCampo>({});

  protected readonly formProducto = this.fb.nonNullable.group({
    nombre: this.fb.nonNullable.control('', [Validators.required]),
    categoria_producto: this.fb.nonNullable.control<number | ''>('', [Validators.required]),
    precio_venta: this.fb.nonNullable.control('', [Validators.required, precioValido]),
    costo: this.fb.nonNullable.control('', [precioValido]),
    marca: this.fb.nonNullable.control(''),
    presentacion: this.fb.nonNullable.control(''),
    stock_minimo: this.fb.nonNullable.control(''),
    activo: this.fb.nonNullable.control(true),
    /** Solo en el ALTA. No es un campo del producto: al guardar se traduce en
     * una entrada de kardex, para no tener que dar de alta y cargar
     * existencias en dos pasos. En edición no aparece -- editar la ficha de
     * un producto no debe mover existencias jamás. */
    existencia_inicial: this.fb.nonNullable.control(''),
  });

  /** La categoría elegida en el formulario, de forma REACTIVA: `control.value`
   * no lo es y un `computed` que lo leyera no volvería a recalcularse. */
  private readonly categoriaElegida = toSignal(
    this.formProducto.controls.categoria_producto.valueChanges,
    { initialValue: this.formProducto.controls.categoria_producto.value },
  );

  /**
   * Categorías ofrecidas en el desplegable del producto: las activas, MÁS la
   * que el producto ya tuviera aunque esté dada de baja.
   *
   * Sin esa excepción, editar un producto de una categoría retirada dejaría
   * el `<select>` sin la opción seleccionada; el control se quedaría con un
   * valor que no figura en la lista, la casilla aparecería vacía y guardar
   * reasignaría el producto sin que nadie lo pidiera.
   */
  protected readonly categoriasParaElegir = computed(() => {
    const elegida = this.categoriaElegida();
    return this.categorias().filter((c) => c.activa || c.id === elegida);
  });

  /**
   * Aviso cuando el costo supera al precio de venta: cada unidad se vendería
   * con pérdida. NO bloquea —una liquidación por debajo de costo es legítima—
   * pero lo normal es que sea un cero de más, y ese error se propaga al
   * kardex y a la utilidad de cada venta, donde ya no se puede corregir.
   */
  private readonly costoTexto = toSignal(this.formProducto.controls.costo.valueChanges, {
    initialValue: this.formProducto.controls.costo.value,
  });
  private readonly precioTexto = toSignal(this.formProducto.controls.precio_venta.valueChanges, {
    initialValue: this.formProducto.controls.precio_venta.value,
  });

  protected readonly costoSuperaPrecio = computed(() => {
    const costo = normalizarPrecio(this.costoTexto() ?? '');
    const precio = normalizarPrecio(this.precioTexto() ?? '');
    if (costo === null || precio === null) {
      return false;
    }
    return Math.round(Number(costo) * 100) > Math.round(Number(precio) * 100);
  });

  // --- Panel de AJUSTE (ya no de entrada: las entradas se registran con
  //     "Registrar compra", que además admite varios productos de una vez) ---
  protected readonly productoMoviendo = signal<Producto | null>(null);
  protected readonly moviendo = signal(false);
  protected readonly errorMovimiento = signal<string | null>(null);

  protected readonly formMovimiento = this.fb.nonNullable.group({
    cantidad: this.fb.nonNullable.control('', [Validators.required]),
    motivo: this.fb.nonNullable.control('', [Validators.required]),
  });

  // --- Compra en lote ---
  protected readonly panelCompra = signal(false);
  protected readonly lineasCompra = signal<LineaCompra[]>([]);
  protected readonly registrandoCompra = signal(false);
  protected readonly errorCompra = signal<string | null>(null);
  protected readonly resumenCompra = signal<string | null>(null);
  protected readonly productoACompra = this.fb.nonNullable.control<number | ''>('');

  protected readonly totalCompra = computed(() =>
    this.lineasCompra().reduce(
      (total, l) => total + Math.round(Number(l.costoUnitario || '0') * 100) * l.cantidad,
      0,
    ),
  );

  // --- Kardex ---
  protected readonly productoKardex = signal<Producto | null>(null);
  protected readonly movimientos = signal<MovimientoInventario[]>([]);
  protected readonly cargandoKardex = signal(false);

  // --- Categorías ---
  protected readonly panelCategorias = signal(false);
  protected readonly nuevaCategoria = this.fb.nonNullable.control('', [Validators.required]);
  protected readonly guardandoCategoria = signal(false);
  protected readonly errorCategoria = signal<string | null>(null);

  constructor() {
    this.buscar.valueChanges
      .pipe(debounceTime(300), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.cargar());

    this.cargarCategorias();
    this.cargar();
  }

  // -----------------------------------------------------------------------
  // Carga
  // -----------------------------------------------------------------------

  protected cargar(): void {
    const sede = this.sedeId();
    if (sede === null) {
      this.cargando.set(false);
      return;
    }
    this.cargando.set(true);
    this.error.set(null);
    this.productosService.listarTodos(sede, this.buscar.value.trim() || undefined).subscribe({
      next: (productos) => {
        this.productos.set(productos);
        this.cargando.set(false);
      },
      error: (error: unknown) => {
        this.cargando.set(false);
        this.error.set(this.mensajeDeError(error, 'No se pudo cargar el inventario.'));
      },
    });
  }

  private cargarCategorias(): void {
    this.productosService.listarCategorias(true).subscribe({
      next: (categorias) => this.categorias.set(categorias),
      error: () => this.categorias.set([]),
    });
  }

  // -----------------------------------------------------------------------
  // Presentación
  // -----------------------------------------------------------------------

  protected dinero(valor: string | undefined | null): string {
    return valor === undefined || valor === null ? '—' : precioParaMostrar(valor);
  }

  /** Cantidad sin decimales cuando son cero: "20" en vez de "20.00". */
  protected cantidad(valor: string): string {
    const numero = Number(valor);
    return Number.isInteger(numero) ? String(numero) : valor;
  }

  protected stockDe(producto: Producto): number {
    return producto.stock === null ? 0 : Number(producto.stock);
  }

  /** `true` si el stock está en el mínimo configurado o por debajo. Se avisa
   * para que reponer no dependa de que alguien se acuerde de mirar. */
  protected bajoMinimo(producto: Producto): boolean {
    const minimo = producto.stock_minimo === null ? 0 : Number(producto.stock_minimo);
    return minimo > 0 && this.stockDe(producto) <= minimo;
  }

  protected fecha(iso: string): string {
    const f = new Date(iso);
    return Number.isNaN(f.getTime())
      ? iso
      : f.toLocaleString('es-CO', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
  }

  protected errorDe(campo: string): string | null {
    const valor = this.erroresCampo()[campo];
    if (!valor) {
      return null;
    }
    return Array.isArray(valor) ? valor[0] : valor;
  }

  protected claseTipo(tipo: TipoMovimiento): string {
    return tipo === 'entrada_compra' || tipo === 'reverso_anulacion' ? 'badge-success' : 'badge-neutral';
  }

  // -----------------------------------------------------------------------
  // Producto
  // -----------------------------------------------------------------------

  protected abrirCreacion(): void {
    this.cerrarPaneles();
    this.productoEditando.set(null);
    this.formProducto.reset({
      nombre: '',
      categoria_producto: '',
      precio_venta: '',
      costo: '',
      marca: '',
      presentacion: '',
      stock_minimo: '',
      activo: true,
      existencia_inicial: '',
    });
    this.panelProducto.set(true);
  }

  protected abrirEdicion(producto: Producto): void {
    this.cerrarPaneles();
    this.productoEditando.set(producto);
    this.formProducto.reset({
      nombre: producto.nombre,
      categoria_producto: producto.categoria_producto ?? '',
      precio_venta: formatearMonto(producto.precio_venta),
      costo: producto.costo === undefined ? '' : formatearMonto(producto.costo),
      marca: producto.marca ?? '',
      presentacion: producto.presentacion ?? '',
      stock_minimo: producto.stock_minimo ?? '',
      activo: producto.activo,
      existencia_inicial: '',
    });
    this.panelProducto.set(true);
  }

  protected cerrarPaneles(): void {
    this.panelProducto.set(false);
    this.productoMoviendo.set(null);
    this.productoKardex.set(null);
    this.panelCategorias.set(false);
    this.panelCompra.set(false);
    this.erroresCampo.set({});
    this.errorMovimiento.set(null);
    this.errorCategoria.set(null);
    this.errorCompra.set(null);
  }

  protected guardarProducto(): void {
    if (this.guardando()) {
      return;
    }
    this.formProducto.markAllAsTouched();
    if (this.formProducto.invalid) {
      return;
    }

    const v = this.formProducto.getRawValue();
    const datos = {
      nombre: v.nombre.trim(),
      categoria_producto: Number(v.categoria_producto),
      precio_venta: normalizarPrecio(v.precio_venta) ?? '0',
      // Los opcionales se envían como `null` cuando se dejan vacíos, no como
      // cadena vacía: el modelo los admite nulos y así no se guardan huecos
      // que luego hay que distinguir del "sin dato".
      marca: v.marca.trim() || null,
      presentacion: v.presentacion.trim() || null,
      ...(v.costo.trim() === '' ? {} : { costo: normalizarPrecio(v.costo) ?? '0' }),
      ...(v.stock_minimo.trim() === '' ? {} : { stock_minimo: v.stock_minimo.trim() }),
      activo: v.activo,
    };

    this.guardando.set(true);
    this.erroresCampo.set({});

    const editando = this.productoEditando();
    const peticion$ = editando
      ? this.productosService.actualizar(editando.id, datos)
      : this.productosService.crear(datos);

    peticion$.subscribe({
      next: (producto) => {
        const inicial = Number(v.existencia_inicial.trim());
        // Solo en el alta y solo si se indicó cantidad: la existencia inicial
        // se traduce en una entrada de kardex, nunca en un stock escrito a
        // mano (ver el comentario del control).
        if (!editando && v.existencia_inicial.trim() !== '' && Number.isFinite(inicial) && inicial > 0) {
          this.cargarConEntradaInicial(producto, inicial, v.costo);
          return;
        }
        this.guardando.set(false);
        this.panelProducto.set(false);
        this.cargar();
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        if (error instanceof HttpErrorResponse && error.status === 400 && error.error) {
          this.erroresCampo.set(error.error as ErroresDeCampo);
          return;
        }
        this.error.set(this.mensajeDeError(error, 'No se pudo guardar el producto.'));
      },
    });
  }

  /**
   * Segundo paso del alta con existencia: registra la entrada por compra.
   *
   * El producto del paso 1 YA EXISTE pase lo que pase aquí. Si esta llamada
   * falla no se oculta el problema ni se finge que no pasó nada: se avisa de
   * que el producto quedó creado con cero existencias y de que hay que
   * cargarlas a mano, que es lo único cierto.
   */
  private cargarConEntradaInicial(producto: Producto, cantidad: number, costo: string): void {
    const sede = this.sedeId();
    if (sede === null) {
      this.guardando.set(false);
      this.panelProducto.set(false);
      this.cargar();
      return;
    }

    this.productosService
      .registrarMovimiento({
        producto_id: producto.id,
        sede_id: sede,
        tipo: 'entrada_compra',
        cantidad: String(cantidad),
        ...(costo.trim() === '' ? {} : { costo_unitario: normalizarPrecio(costo) ?? '0' }),
      })
      .subscribe({
        next: () => {
          this.guardando.set(false);
          this.panelProducto.set(false);
          this.cargar();
        },
        error: (error: unknown) => {
          this.guardando.set(false);
          this.panelProducto.set(false);
          this.error.set(
            `Se creó "${producto.nombre}", pero no se pudo cargar la existencia inicial ` +
              `(${this.mensajeDeError(error, 'error desconocido')}). Añádela desde el icono de caja.`,
          );
          this.cargar();
        },
      });
  }

  protected darDeBaja(producto: Producto): void {
    const confirmado = confirm(
      `¿Dar de baja "${producto.nombre}"? Dejará de estar disponible en el punto de venta; ` +
        'las ventas ya registradas no se ven afectadas.',
    );
    if (!confirmado) {
      return;
    }
    this.error.set(null);
    this.productosService.eliminar(producto.id).subscribe({
      next: () => this.cargar(),
      error: (error: unknown) =>
        this.error.set(this.mensajeDeError(error, 'No se pudo dar de baja el producto.')),
    });
  }

  /** Devuelve un producto al catálogo.
   *
   * Se podía hacer editándolo y marcando la casilla "Activo", pero en la fila
   * de un producto dado de baja el único botón visible era "Dar de baja"
   * —que ya no hacía nada—, así que la vuelta atrás quedaba escondida dentro
   * de un formulario. Sin confirmación: reactivar no destruye nada. */
  protected reactivar(producto: Producto): void {
    this.error.set(null);
    this.productosService.actualizar(producto.id, { activo: true }).subscribe({
      next: () => this.cargar(),
      error: (error: unknown) =>
        this.error.set(this.mensajeDeError(error, 'No se pudo reactivar el producto.')),
    });
  }

  // -----------------------------------------------------------------------
  // Movimientos
  // -----------------------------------------------------------------------

  // -----------------------------------------------------------------------
  // Ajuste (merma, conteo físico, corrección)
  // -----------------------------------------------------------------------

  protected abrirMovimiento(producto: Producto): void {
    this.cerrarPaneles();
    this.formMovimiento.reset({ cantidad: '', motivo: '' });
    this.productoMoviendo.set(producto);
  }

  protected registrarMovimiento(): void {
    const producto = this.productoMoviendo();
    const sede = this.sedeId();
    if (this.moviendo() || producto === null || sede === null) {
      return;
    }
    this.formMovimiento.markAllAsTouched();
    if (this.formMovimiento.invalid) {
      return;
    }

    const v = this.formMovimiento.getRawValue();
    const cantidad = Number(v.cantidad);
    if (!Number.isFinite(cantidad) || cantidad === 0) {
      this.errorMovimiento.set('La cantidad no puede ser cero.');
      return;
    }

    this.moviendo.set(true);
    this.errorMovimiento.set(null);

    this.productosService
      .registrarMovimiento({
        producto_id: producto.id,
        sede_id: sede,
        // Este panel es SOLO de ajuste: las entradas tienen sus dos caminos
        // propios (reposición rápida y compra en lote).
        tipo: 'ajuste_manual',
        cantidad: String(cantidad),
        motivo: v.motivo.trim(),
      })
      .subscribe({
        next: () => {
          this.moviendo.set(false);
          this.productoMoviendo.set(null);
          this.cargar();
        },
        error: (error: unknown) => {
          this.moviendo.set(false);
          this.errorMovimiento.set(this.mensajeDeError(error, 'No se pudo registrar el movimiento.'));
        },
      });
  }

  // -----------------------------------------------------------------------
  // Compra en lote: "llegó el pedido"
  // -----------------------------------------------------------------------

  protected abrirCompra(): void {
    this.cerrarPaneles();
    this.lineasCompra.set([]);
    this.productoACompra.setValue('');
    this.resumenCompra.set(null);
    this.panelCompra.set(true);
  }

  protected agregarLineaCompra(): void {
    const id = Number(this.productoACompra.value);
    const producto = this.productos().find((p) => p.id === id);
    if (!producto) {
      return;
    }
    if (this.lineasCompra().some((l) => l.producto.id === id)) {
      this.errorCompra.set(`"${producto.nombre}" ya está en la lista; cambia su cantidad.`);
      return;
    }
    this.errorCompra.set(null);
    this.lineasCompra.update((lineas) => [
      ...lineas,
      {
        producto,
        cantidad: 1,
        costoUnitario: producto.costo === undefined ? '' : producto.costo,
      },
    ]);
    this.productoACompra.setValue('');
  }

  protected cambiarCantidadCompra(linea: LineaCompra, valor: string): void {
    const cantidad = Number(valor);
    this.lineasCompra.update((lineas) =>
      lineas.map((l) => (l === linea ? { ...l, cantidad: Number.isFinite(cantidad) ? cantidad : 0 } : l)),
    );
  }

  protected cambiarCostoCompra(linea: LineaCompra, valor: string): void {
    const normalizado = normalizarPrecio(valor);
    this.lineasCompra.update((lineas) =>
      lineas.map((l) => (l === linea ? { ...l, costoUnitario: normalizado ?? '' } : l)),
    );
  }

  protected quitarLineaCompra(linea: LineaCompra): void {
    this.lineasCompra.update((lineas) => lineas.filter((l) => l !== linea));
  }

  /**
   * Registra una entrada por cada línea.
   *
   * Van EN SERIE (`concatMap`), no en paralelo: el disparador de stock bloquea
   * la fila de existencias de cada producto, y lanzarlas a la vez solo
   * añadiría contención sin ganar tiempo real.
   *
   * No es atómico: son N peticiones independientes, así que unas pueden
   * cuajar y otras no. En vez de fingir que fue todo o nada, cada línea
   * captura su propio error y al final se informa exactamente de cuántas
   * entraron y cuáles fallaron.
   */
  protected registrarCompra(): void {
    const sede = this.sedeId();
    const lineas = this.lineasCompra();
    if (this.registrandoCompra() || sede === null || lineas.length === 0) {
      return;
    }
    const invalida = lineas.find((l) => !Number.isFinite(l.cantidad) || l.cantidad <= 0);
    if (invalida) {
      this.errorCompra.set(`"${invalida.producto.nombre}" necesita una cantidad mayor que cero.`);
      return;
    }

    this.registrandoCompra.set(true);
    this.errorCompra.set(null);
    this.resumenCompra.set(null);

    from(lineas)
      .pipe(
        concatMap((linea) =>
          this.productosService
            .registrarMovimiento({
              producto_id: linea.producto.id,
              sede_id: sede,
              tipo: 'entrada_compra',
              cantidad: String(linea.cantidad),
              ...(linea.costoUnitario === '' ? {} : { costo_unitario: linea.costoUnitario }),
            })
            .pipe(
              concatMap(() => of({ ok: true, nombre: linea.producto.nombre })),
              catchError(() => of({ ok: false, nombre: linea.producto.nombre })),
            ),
        ),
        toArray(),
      )
      .subscribe((resultados) => {
        this.registrandoCompra.set(false);
        const fallidas = resultados.filter((r) => !r.ok).map((r) => r.nombre);
        const correctas = resultados.length - fallidas.length;
        if (fallidas.length === 0) {
          this.panelCompra.set(false);
          this.resumenCompra.set(`Compra registrada: ${correctas} producto(s) actualizados.`);
        } else {
          this.errorCompra.set(
            `Entraron ${correctas} de ${resultados.length}. Falló: ${fallidas.join(', ')}. ` +
              'Las que sí entraron ya están registradas; revisa y reintenta solo las que faltan.',
          );
          this.lineasCompra.update((ls) => ls.filter((l) => fallidas.includes(l.producto.nombre)));
        }
        this.cargar();
      });
  }

  // -----------------------------------------------------------------------
  // Kardex
  // -----------------------------------------------------------------------

  protected abrirKardex(producto: Producto): void {
    this.cerrarPaneles();
    this.productoKardex.set(producto);
    this.cargandoKardex.set(true);
    this.productosService
      .listarMovimientos({ producto: producto.id, sede: this.sedeId() ?? undefined })
      .subscribe({
        next: (movimientos) => {
          this.movimientos.set(movimientos);
          this.cargandoKardex.set(false);
        },
        error: () => {
          this.movimientos.set([]);
          this.cargandoKardex.set(false);
        },
      });
  }

  // -----------------------------------------------------------------------
  // Categorías
  // -----------------------------------------------------------------------

  protected abrirCategorias(): void {
    this.cerrarPaneles();
    this.nuevaCategoria.setValue('');
    this.panelCategorias.set(true);
  }

  protected crearCategoria(): void {
    if (this.guardandoCategoria() || this.nuevaCategoria.invalid) {
      this.nuevaCategoria.markAsTouched();
      return;
    }
    this.guardandoCategoria.set(true);
    this.errorCategoria.set(null);
    this.productosService.crearCategoria({ nombre: this.nuevaCategoria.value.trim() }).subscribe({
      next: () => {
        this.guardandoCategoria.set(false);
        this.nuevaCategoria.setValue('');
        this.cargarCategorias();
      },
      error: (error: unknown) => {
        this.guardandoCategoria.set(false);
        this.errorCategoria.set(this.mensajeDeError(error, 'No se pudo crear la categoría.'));
      },
    });
  }

  protected darDeBajaCategoria(categoria: CategoriaProducto): void {
    if (!confirm(`¿Dar de baja la categoría "${categoria.nombre}"?`)) {
      return;
    }
    this.errorCategoria.set(null);
    this.productosService.eliminarCategoria(categoria.id).subscribe({
      next: () => this.cargarCategorias(),
      error: (error: unknown) =>
        this.errorCategoria.set(this.mensajeDeError(error, 'No se pudo dar de baja la categoría.')),
    });
  }

  /** Vuelve a poner en circulación una categoría dada de baja. No se pide
   * confirmación: reactivar no destruye nada y se deshace dándola de baja
   * otra vez. */
  protected reactivarCategoria(categoria: CategoriaProducto): void {
    this.errorCategoria.set(null);
    this.productosService.actualizarCategoria(categoria.id, { activa: true }).subscribe({
      next: () => this.cargarCategorias(),
      error: (error: unknown) =>
        this.errorCategoria.set(this.mensajeDeError(error, 'No se pudo reactivar la categoría.')),
    });
  }

  private mensajeDeError(error: unknown, porDefecto: string): string {
    if (error instanceof HttpErrorResponse && error.error) {
      const cuerpo = error.error as Record<string, unknown>;
      if (typeof cuerpo['detail'] === 'string') {
        return cuerpo['detail'];
      }
      const primero = Object.values(cuerpo)[0];
      if (typeof primero === 'string') {
        return primero;
      }
      if (Array.isArray(primero) && typeof primero[0] === 'string') {
        return primero[0];
      }
    }
    return porDefecto;
  }
}
